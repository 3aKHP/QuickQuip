"""LLM 回复消息拼装：文本 + 工具外发图片。

群聊两个触发路径与私聊路径共用，保证带图回复的拼装逻辑只写一份。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
