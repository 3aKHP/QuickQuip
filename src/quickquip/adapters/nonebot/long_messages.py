from __future__ import annotations

import asyncio
import logging

from quickquip.adapters.nonebot._safe_send import send_group_image, send_group_text
from quickquip.common.sensitive_filter import DEFAULT_OUTPUT_FALLBACK, scan_and_log
from quickquip.common.text_image import render_text_to_image

logger = logging.getLogger(__name__)

# OneBot 协议实现端（NapCat / LLBot）在单条节点超过 ~2 KB 时可能截断。
# 按段落 / 换行拆分，保持在限制以内。
_MAX_SEND_CHARS = 800
_IMAGE_FALLBACK_FOOTER = "合并转发不可用，已转为长图发送"


def split_long_message(content: str, max_chars: int = _MAX_SEND_CHARS) -> list[str]:
    if len(content) <= max_chars:
        return [content]

    chunks: list[str] = []
    remaining = content
    while len(remaining) > max_chars:
        pos = remaining.rfind("\n\n", 0, max_chars)
        if pos != -1:
            chunks.append(remaining[:pos].rstrip())
            remaining = remaining[pos + 2:].lstrip()
            continue
        pos = remaining.rfind("\n", 0, max_chars)
        if pos != -1:
            chunks.append(remaining[:pos])
            remaining = remaining[pos + 1:]
            continue
        chunks.append(remaining[:max_chars])
        remaining = remaining[max_chars:]
    if remaining.strip():
        chunks.append(remaining.strip())
    return chunks


async def send_long_group_message(
    bot,
    group_id: int,
    content: str,
    *,
    node_name: str,
    log_name: str,
) -> None:
    """优先以群合并转发发送长文；失败时降级渲染为单张长图发送，避免多条文本刷屏。"""
    scan_result = scan_and_log(
        content,
        channel=f"outbound_long:{log_name}",
        scope=str(group_id),
    )
    if scan_result.blocked:
        await send_group_text(bot, group_id, DEFAULT_OUTPUT_FALLBACK)
        return
    chunks = split_long_message(content)
    try:
        await bot.call_api(
            "send_group_forward_msg",
            group_id=group_id,
            messages=[
                {
                    "type": "node",
                    "data": {
                        "name": node_name,
                        "uin": str(bot.self_id),
                        "content": [{"type": "text", "data": {"text": chunk}}],
                    },
                }
                for chunk in chunks
            ],
        )
    except Exception:
        logger.warning("%s: forward msg failed, falling back to long image", log_name)
        image_bytes = await asyncio.to_thread(
            render_text_to_image,
            content,
            title=node_name,
            footer=_IMAGE_FALLBACK_FOOTER,
        )
        await send_group_image(bot, group_id, image_bytes)
