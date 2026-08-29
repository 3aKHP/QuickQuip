"""安全群发送：纯文本一律走 text 段，杜绝裸 str 被服务端按 CQ 码解析。

matcher.send 会把 str 安全包装成文本段，但直调 ``bot.send_group_msg`` 等 API 时
裸 str 会以 CQ 码字符串格式传输，文本里的 ``[CQ:...]`` 字面量会被激活成真实段。
本模块的 helper 统一以 array 段格式发送纯文本，与 #138 的复读修复语义一致。
"""

from __future__ import annotations

from nonebot.adapters.onebot.v11 import Message, MessageSegment


async def send_group_text(bot, group_id: int, text: str) -> None:
    """以单 text 段发送群纯文本（array 段格式）。

    必须包成 ``Message``：裸 MessageSegment 会被 DataclassEncoder 序列化成
    单个对象而非段数组，不符合 OneBot V11 的 message 规范（string | array）。
    """
    await bot.send_group_msg(group_id=group_id, message=Message([MessageSegment.text(text)]))


async def send_private_text(bot, user_id: int, text: str) -> None:
    """以单 text 段发送私聊纯文本（与 :func:`send_group_text` 同理）。"""
    await bot.send_private_msg(user_id=user_id, message=Message([MessageSegment.text(text)]))
