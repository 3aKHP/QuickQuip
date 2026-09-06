"""LLM 回复消息拼装：文本 + 工具外发图片 + 生产 DeliverySink。

群聊两个触发路径与私聊路径共用，保证带图回复的拼装逻辑只写一份。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from quickquip.llm.agent_records import DeliveryReceipt, DeliveryStatus

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message as OneBotMessage
    from nonebot.adapters.onebot.v11 import MessageSegment as OneBotMessageSegment


def build_llm_reply_message(
    result: dict[str, Any],
    Message: type[OneBotMessage],
    MessageSegment: type[OneBotMessageSegment],
) -> OneBotMessage:
    """把 ``generate_reply`` 的结果转为可发送内容，恒为 Message。

    无图也返回单 text 段的 Message：裸 str 直调 bot.send_* API 时会被服务端
    按 CQ 码解析（matcher.send 才会安全包装 str），恒返回 Message 让直发与
    matcher 路径的传输语义一致（array 段格式）。
    """
    segments = [MessageSegment.text(result["reply"])]
    segments.extend(
        MessageSegment.image(f"base64://{b64}") for b64 in result.get("images") or []
    )
    return Message(segments)


# 同 scope 相邻发送开始时间的最小间隔（§6.2）：进程内节流表。
_LAST_SEND_AT: dict[str, float] = {}

_DEFAULT_INTERVAL_MS = 800


def reply_interval_ms(svc: Any) -> int:
    """读取 reply_send_interval_ms；svc 为测试桩时回落默认值。"""
    try:
        return int(getattr(svc.config.runtime, "reply_send_interval_ms", _DEFAULT_INTERVAL_MS))
    except (AttributeError, TypeError, ValueError):
        return _DEFAULT_INTERVAL_MS


def reset_delivery_throttle() -> None:
    """测试隔离用：清空节流表。"""
    _LAST_SEND_AT.clear()


class OneBotDeliverySink:
    """生产 DeliverySink（§5.1/§6.2）。

    ``send`` 是适配层注入的单条文本发送协程（matcher.send 或
    bot.send_group_msg/send_private_msg 的薄包装），回执分类：

    - dict 且含可信 ``message_id`` → ``sent``；
    - 响应缺 message_id / 超时类异常 → ``unknown``（不自动重发）；
    - 其余显式失败 → ``failed``。

    正文经 ``MessageSegment.text`` 构造，不进 CQ 解析器。相邻发送按
    ``reply_send_interval_ms`` 节流，不并发发送同一 scope 的片段。
    """

    def __init__(
        self,
        send: Callable[[str], Awaitable[Any]],
        *,
        scope_key: str,
        interval_ms: int = 800,
    ) -> None:
        self._send = send
        self._scope_key = scope_key
        self._interval_seconds = max(0, int(interval_ms)) / 1000.0
        # 仅成功回执的可见文本：供冷却缓存/trace 预览消费；失败不污染
        # （零成功交付不得触发冷却确认）。
        self.sent_texts: list[str] = []

    async def __call__(self, delivery_id: str, payload: dict[str, Any]) -> DeliveryReceipt:
        text = str(payload.get("text", ""))
        if self._interval_seconds:
            last = _LAST_SEND_AT.get(self._scope_key)
            if last is not None:
                wait = self._interval_seconds - (time.monotonic() - last)
                if wait > 0:
                    await asyncio.sleep(wait)
            _LAST_SEND_AT[self._scope_key] = time.monotonic()
        try:
            resp = await self._send(text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            lowered = str(exc).lower()
            if "timeout" in lowered or "timed out" in lowered:
                return DeliveryReceipt(status=DeliveryStatus.UNKNOWN, error_code=type(exc).__name__)
            return DeliveryReceipt(status=DeliveryStatus.FAILED, error_code=type(exc).__name__)
        self.sent_texts.append(text)
        message_id = ""
        if isinstance(resp, dict):
            message_id = str(resp.get("message_id", "") or "").strip()
        if message_id:
            return DeliveryReceipt(status=DeliveryStatus.SENT, message_id=message_id)
        return DeliveryReceipt(status=DeliveryStatus.UNKNOWN, error_code="missing_message_id")


def text_only_message(text: str, Message: type[OneBotMessage], MessageSegment: type[OneBotMessageSegment]) -> OneBotMessage:
    """纯文本 Message（§6.2）：分段正文不经 CQ 解析器。"""
    return Message([MessageSegment.text(text)])


def make_matcher_sink(matcher, Message, MessageSegment, *, scope_key: str, interval_ms: int) -> OneBotDeliverySink:
    return OneBotDeliverySink(
        lambda text: matcher.send(text_only_message(text, Message, MessageSegment)),
        scope_key=scope_key,
        interval_ms=interval_ms,
    )


def make_group_bot_sink(bot, Message, MessageSegment, *, group_id: int | str, interval_ms: int) -> OneBotDeliverySink:
    async def _send(text: str):
        return await bot.send_group_msg(
            group_id=int(group_id),
            message=text_only_message(text, Message, MessageSegment),
        )

    return OneBotDeliverySink(_send, scope_key=str(group_id), interval_ms=interval_ms)


def make_private_bot_sink(bot, Message, MessageSegment, *, user_id: int | str, interval_ms: int) -> OneBotDeliverySink:
    async def _send(text: str):
        return await bot.send_private_msg(
            user_id=int(user_id),
            message=text_only_message(text, Message, MessageSegment),
        )

    return OneBotDeliverySink(_send, scope_key=f"private:{user_id}", interval_ms=interval_ms)


def record_final_receipt(svc, result: dict[str, Any], sent_msg_id: str) -> None:
    """关闭开关模式下的最终单发回执：新链路用确切 row_id 回填兼容列（§4.1）。"""
    import logging as _logging

    row_id = result.get("agent_turn_row_id")
    if row_id and sent_msg_id:
        try:
            svc.store.set_first_chunk_message_id(int(row_id), sent_msg_id)
            return
        except Exception:
            _logging.getLogger(__name__).warning(
                "final receipt backfill failed for row %s", row_id, exc_info=True
            )
            return
    if sent_msg_id:
        scope_key = str(result.get("scope_key", "")) or None
        if scope_key:
            svc.store.update_last_assistant_message_id(scope_key, sent_msg_id)
