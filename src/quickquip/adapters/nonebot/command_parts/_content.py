from __future__ import annotations


def _extract_image_urls(message) -> list[str]:
    return [
        seg.data.get("url", "")
        for seg in message
        if seg.type == "image" and seg.data.get("url", "").startswith("http")
    ]


async def _resolve_forward_content(bot, seg) -> tuple[str, list[str]]:
    raw_nodes = seg.data.get("content") or []
    if not raw_nodes:
        fwd_id = seg.data.get("id", "")
        if fwd_id:
            try:
                raw_nodes = await bot.get_forward_msg(message_id=fwd_id) or []
            except Exception:
                return "", []
    texts: list[str] = []
    urls: list[str] = []
    for node in raw_nodes:
        if not isinstance(node, dict):
            continue
        for sd in node.get("message", []):
            if not isinstance(sd, dict):
                continue
            if sd.get("type") == "text":
                t = sd.get("data", {}).get("text", "").strip()
                if t:
                    texts.append(t)
            elif sd.get("type") == "image":
                url = sd.get("data", {}).get("url", "")
                if url.startswith("http"):
                    urls.append(url)
    return "\n".join(filter(None, texts)), urls


async def _resolve_message_content(bot, message) -> tuple[str, list[str]]:
    texts: list[str] = []
    urls: list[str] = []
    for seg in message:
        if seg.type == "text":
            t = seg.data.get("text", "").strip()
            if t:
                texts.append(t)
        elif seg.type == "image":
            url = seg.data.get("url", "")
            if url.startswith("http"):
                urls.append(url)
        elif seg.type == "forward":
            ft, fu = await _resolve_forward_content(bot, seg)
            if ft:
                texts.append(ft)
            urls.extend(fu)
    return "\n".join(filter(None, texts)), urls
