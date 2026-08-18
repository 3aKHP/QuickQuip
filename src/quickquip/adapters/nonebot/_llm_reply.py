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
) -> str | OneBotMessage:
    """把 ``generate_reply`` 的结果转为可发送内容：无图时返回纯文本，有图时返回 Message。"""
    images = result.get("images") or []
    if not images:
        return result["reply"]
    segments = [MessageSegment.text(result["reply"])]
    segments.extend(
        MessageSegment.image(f"base64://{b64}") for b64 in images
    )
    return Message(segments)
