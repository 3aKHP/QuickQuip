"""LLM 回复消息拼装：文本 + 出站提及解析 + 引用段 + 生产 DeliverySink。

群聊两个触发路径与私聊路径共用，保证带图回复的拼装逻辑只写一份。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

try:
    from nonebot.exception import ActionFailed
except ModuleNotFoundError:  # pragma: no cover - 无 nonebot 环境下不存在可捕获的 ActionFailed
    ActionFailed = None

from quickquip.llm.agent_records import DeliveryReceipt, DeliveryStatus

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message as OneBotMessage
    from nonebot.adapters.onebot.v11 import MessageSegment as OneBotMessageSegment

logger = logging.getLogger(__name__)

# 模型可能沿用输入形态输出「@QQ 号」（裸数字艾特）；发送前切分为真实
# at 段，保证被艾特成员在客户端得到高亮与名字而非纯数字文本。
# 右边界 (?!\d)：超过 12 位的数字串（幻觉长号）不切分，保持原文本。
_OUTBOUND_AT_QQ_PATTERN = re.compile(r"@QQ(\d{5,12})(?!\d)")

# 名字通道（「@名字」→ 真实艾特）的护栏：
# - 单条消息真实艾特数量上限（数字通道与名字通道合计），超出降级为文本；
# - 同一 (scope, qq) 在冷却窗内只真实艾特一次，窗内后续提及降级为文本；
# - 候选名最长探测长度（超出长度的名字不参与解析）。
_DEFAULT_MAX_MENTIONS = 3
_MENTION_COOLDOWN_SECONDS = 600.0
_MAX_MENTION_NAME_LENGTH = 24
_LAST_MENTION_AT: dict[tuple[str, int], float] = {}


def split_outbound_mentions(
    text: str,
    Message: type[OneBotMessage],
    MessageSegment: type[OneBotMessageSegment],
    *,
    resolve_mention: Callable[[str], tuple[int, int] | None] | None = None,
    max_mentions: int = _DEFAULT_MAX_MENTIONS,
) -> list[Any]:
    """把文本中的提及标记切分为 ``MessageSegment.at`` 与文本段。

    两个通道：数字通道（``@QQ号``，恒生效）与名字通道（``@名字``，
    需注入 ``resolve_mention``）。resolver 接收 @ 后的文本，返回
    ``(qq, 消耗字符数)`` 或 None（该位置原样保留文本）。真实艾特总数
    达到 ``max_mentions`` 后，其余提及一律保留为文本。
    """
    segments: list[Any] = []
    cursor = 0
    pos = 0
    mentions = 0
    while mentions < max_mentions:
        at = text.find("@", pos)
        if at < 0:
            break
        target: tuple[int, int] | None = None
        match = _OUTBOUND_AT_QQ_PATTERN.match(text, at)
        if match:
            target = (int(match.group(1)), match.end())
        elif resolve_mention is not None:
            resolved = resolve_mention(text[at + 1 :])
            if resolved is not None:
                target = (resolved[0], at + 1 + resolved[1])
        if target is None:
            pos = at + 1
            continue
        qq, end = target
        if at > cursor:
            segments.append(MessageSegment.text(text[cursor:at]))
        segments.append(MessageSegment.at(qq))
        mentions += 1
        cursor = pos = end
    if cursor < len(text):
        segments.append(MessageSegment.text(text[cursor:]))
    return segments or [MessageSegment.text(text)]


def make_mention_resolver(
    snapshot,
    *,
    bot_qq: str | int | None = None,
    scope_key: str = "",
    cooldown_seconds: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Callable[[str], tuple[int, int] | None]:
    """构建「@名字」解析器：输入 @ 后的文本，返回 ``(qq, 消耗字符数)``。

    在身份快照的已知名字（标准身份、别名、观察名片）上做最长匹配；
    命中已知名字后不再向更短名字回退——歧义、艾特 bot 自身、冷却窗内
    重复艾特同一人都使整段提及保留为文本。at-all 在结构上不可达：
    本解析器只产出快照内的 int QQ。纯数字与 ``QQ<数字>`` 形态的名字
    不参与解析（数字通道由扫描器的 @QQ 正则独占，防幻觉长号）。
    """
    cooldown = _MENTION_COOLDOWN_SECONDS if cooldown_seconds is None else float(cooldown_seconds)
    names: set[str] = set()
    index = getattr(snapshot, "index", None)
    for entry in getattr(index, "entries", None) or []:
        names.add(str(getattr(entry, "canonical_name", "") or ""))
        names.update(str(alias or "") for alias in (getattr(entry, "aliases", None) or []))
    names.update(str(name or "") for name in (getattr(snapshot, "names", None) or {}).values())
    names = {
        name.strip()
        for name in names
        if name
        and name.strip()
        and len(name.strip()) <= _MAX_MENTION_NAME_LENGTH
        and not name.strip().isdigit()
        and not (name.strip().startswith("QQ") and name.strip()[2:].isdigit())
    }
    lengths = sorted({len(name) for name in names}, reverse=True)
    bot_key = str(bot_qq or "")

    def resolve(text_after_at: str) -> tuple[int, int] | None:
        if not text_after_at:
            return None
        for length in lengths:
            if length > len(text_after_at):
                continue
            candidate = text_after_at[:length]
            if candidate not in names:
                continue
            try:
                qqs = snapshot.candidates(candidate)
                if not qqs or snapshot.ambiguous(qqs):
                    return None
            except Exception:
                logger.warning("出站提及解析失败：%r", candidate, exc_info=True)
                return None
            qq = sorted(qqs)[0]
            if bot_key and qq == bot_key:
                return None
            try:
                qq_int = int(qq)
            except (TypeError, ValueError):
                return None
            key = (scope_key, qq_int)
            now = clock()
            last = _LAST_MENTION_AT.get(key)
            if last is not None and now - last < cooldown:
                return None
            _LAST_MENTION_AT[key] = now
            return (qq_int, length)
        return None

    return resolve


def reset_mention_cooldowns() -> None:
    """测试隔离用：清空艾特冷却表。"""
    _LAST_MENTION_AT.clear()


def mention_cooldown_seconds(svc: Any) -> float:
    """读取 mention_cooldown_seconds；svc 为测试桩时回落默认值。"""
    try:
        return float(
            getattr(svc.config.runtime, "mention_cooldown_seconds", _MENTION_COOLDOWN_SECONDS)
        )
    except (AttributeError, TypeError, ValueError):
        return _MENTION_COOLDOWN_SECONDS


def _normalize_reply_id(reply_to_message_id: Any) -> int | None:
    """把 OneBot message_id 归一化为 int；非法值按无引用处理。"""
    if reply_to_message_id is None:
        return None
    if isinstance(reply_to_message_id, int):
        return reply_to_message_id
    try:
        return int(str(reply_to_message_id).strip())
    except (TypeError, ValueError):
        logger.warning("引用消息 id 非法，按无引用发送：%r", reply_to_message_id)
        return None


async def send_with_reply_fallback(
    send: Callable[[Any], Awaitable[Any]],
    message: OneBotMessage,
    *,
    reply_to_message_id: Any,
    Message: type[OneBotMessage],
    MessageSegment: type[OneBotMessageSegment],
) -> Any:
    """带引用段发送：协议端显式拒绝（ActionFailed）时去段重发，正文必达。

    超时等传输层异常不重试（消息可能已发出，重发会导致重复），沿用
    DeliverySink 对超时的既有 UNKNOWN 语义。
    """
    reply_id = _normalize_reply_id(reply_to_message_id)
    if reply_id is None:
        return await send(message)
    quoted = Message([MessageSegment.reply(reply_id), *message])
    try:
        return await send(quoted)
    except Exception as exc:
        if ActionFailed is None or not isinstance(exc, ActionFailed):
            raise
        logger.warning("引用段发送被协议端拒绝，去引用重发正文", exc_info=True)
        return await send(message)


def build_llm_reply_message(
    result: dict[str, Any],
    Message: type[OneBotMessage],
    MessageSegment: type[OneBotMessageSegment],
    *,
    resolve_mention: Callable[[str], tuple[int, int] | None] | None = None,
) -> OneBotMessage:
    """把 ``generate_reply`` 的结果转为可发送内容，恒为 Message。

    无图也返回单 text 段的 Message：裸 str 直调 bot.send_* API 时会被服务端
    按 CQ 码解析（matcher.send 才会安全包装 str），恒返回 Message 让直发与
    matcher 路径的传输语义一致（array 段格式）。
    """
    segments = split_outbound_mentions(
        str(result["reply"]), Message, MessageSegment, resolve_mention=resolve_mention
    )
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
        message_id = ""
        if isinstance(resp, dict):
            message_id = str(resp.get("message_id", "") or "").strip()
        if message_id:
            # Only a trusted message id confirms a visible delivery.  An
            # otherwise successful transport response without one is unknown
            # and must not feed cooldowns, previews, or delivery statistics.
            self.sent_texts.append(text)
            return DeliveryReceipt(status=DeliveryStatus.SENT, message_id=message_id)
        return DeliveryReceipt(status=DeliveryStatus.UNKNOWN, error_code="missing_message_id")


def text_only_message(
    text: str,
    Message: type[OneBotMessage],
    MessageSegment: type[OneBotMessageSegment],
    *,
    resolve_mention: Callable[[str], tuple[int, int] | None] | None = None,
) -> OneBotMessage:
    """纯文本 Message（§6.2）：分段正文不经 CQ 解析器。

    正文中的提及标记在此出口切分为真实 at 段（分段交付与
    定时/唤醒等全部 sink 路径共用本出口）。
    """
    return Message(
        split_outbound_mentions(text, Message, MessageSegment, resolve_mention=resolve_mention)
    )


def make_matcher_sink(
    matcher,
    Message,
    MessageSegment,
    *,
    scope_key: str,
    interval_ms: int,
    reply_to_message_id: Any = None,
    resolve_mention: Callable[[str], tuple[int, int] | None] | None = None,
) -> OneBotDeliverySink:
    reply_id = _normalize_reply_id(reply_to_message_id)

    async def _send(text: str):
        nonlocal reply_id
        message = text_only_message(text, Message, MessageSegment, resolve_mention=resolve_mention)
        # 引用段只挂首个 chunk：消费后即置空，后续 chunk 纯文本。
        current, reply_id = reply_id, None
        return await send_with_reply_fallback(
            matcher.send, message,
            reply_to_message_id=current, Message=Message, MessageSegment=MessageSegment,
        )

    return OneBotDeliverySink(_send, scope_key=scope_key, interval_ms=interval_ms)


def make_group_bot_sink(
    bot,
    Message,
    MessageSegment,
    *,
    group_id: int | str,
    interval_ms: int,
    reply_to_message_id: Any = None,
    resolve_mention: Callable[[str], tuple[int, int] | None] | None = None,
) -> OneBotDeliverySink:
    reply_id = _normalize_reply_id(reply_to_message_id)

    async def _send_message(message) -> Any:
        return await bot.send_group_msg(group_id=int(group_id), message=message)

    async def _send(text: str):
        nonlocal reply_id
        message = text_only_message(text, Message, MessageSegment, resolve_mention=resolve_mention)
        current, reply_id = reply_id, None
        return await send_with_reply_fallback(
            _send_message, message,
            reply_to_message_id=current, Message=Message, MessageSegment=MessageSegment,
        )

    return OneBotDeliverySink(_send, scope_key=str(group_id), interval_ms=interval_ms)


def make_private_bot_sink(
    bot, Message, MessageSegment, *, user_id: int | str, interval_ms: int
) -> OneBotDeliverySink:
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
