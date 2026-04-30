from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# NapCat silently truncates single text messages beyond ~2 KB (~667 Chinese chars).
# Split at paragraph / line boundaries to stay well under that limit.
_MAX_SEND_CHARS = 800


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
        logger.warning("%s: forward msg failed, falling back to chunked send", log_name)
        for chunk in chunks:
            await bot.send_group_msg(group_id=group_id, message=chunk)
            await asyncio.sleep(0.5)
