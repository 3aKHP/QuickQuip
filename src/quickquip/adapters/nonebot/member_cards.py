"""群成员名片缓存：为未登记成员的 @ 提及提供显示名回退。

OneBot at 段只携带 QQ 号；身份索引未登记的成员要拿到其群名片需调
``get_group_member_info``。按（群号, QQ）带 TTL 缓存，负结果同样缓存，
避免热路径反复请求协议端。查询失败的成员由 ``render_mention`` 回退
``@QQ 号`` 数字形态并保持静默（计入正常降级路径）。
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_MEMBER_CARD_TTL_SECONDS = 3600.0
_MEMBER_CARD_CACHE_MAX = 512
_MAX_FETCH_PER_MESSAGE = 5

_card_cache: dict[tuple[str, str], tuple[float, str]] = {}


def _cache_get(group_id: str, qq: str) -> str | None:
    hit = _card_cache.get((group_id, qq))
    if hit is None:
        return None
    cached_at, card = hit
    if time.monotonic() - cached_at >= _MEMBER_CARD_TTL_SECONDS:
        _card_cache.pop((group_id, qq), None)
        return None
    return card


def _cache_put(group_id: str, qq: str, card: str) -> None:
    if len(_card_cache) >= _MEMBER_CARD_CACHE_MAX:
        oldest = min(_card_cache, key=lambda key: _card_cache[key][0])
        _card_cache.pop(oldest, None)
    _card_cache[(group_id, qq)] = (time.monotonic(), card)


def reset_member_card_cache() -> None:
    """测试隔离用：清空名片缓存。"""
    _card_cache.clear()


async def fetch_mention_names(
    bot: Any,
    group_id: int | str,
    at_qq_ids: list[str],
    *,
    is_registered,
) -> dict[str, str]:
    """为 ``at_qq_ids`` 中未登记的 QQ 取群名片。

    ``is_registered`` 为 ``(qq: str) -> bool`` 判定函数（身份索引注入），
    已登记成员的 @ 提及由标准身份渲染，无需查名片。单条消息最多查
    ``_MAX_FETCH_PER_MESSAGE`` 个，超出者本轮放弃（回退数字形态）。
    """
    group_key = str(group_id)
    names: dict[str, str] = {}
    to_fetch: list[str] = []
    for qq in at_qq_ids:
        qq = qq.strip()
        if not qq or not qq.isdigit() or is_registered(qq):
            continue
        cached = _cache_get(group_key, qq)
        if cached is not None:
            if cached:
                names[qq] = cached
            continue
        if qq not in to_fetch:
            to_fetch.append(qq)

    for qq in to_fetch[:_MAX_FETCH_PER_MESSAGE]:
        card = ""
        try:
            info = await bot.get_group_member_info(
                group_id=int(group_id), user_id=int(qq)
            )
            if isinstance(info, dict):
                card = str(info.get("card", "") or "").strip()
                if not card:
                    card = str(info.get("nickname", "") or "").strip()
        except Exception:
            logger.debug("群成员名片查询失败 group=%s qq=%s", group_key, qq)
        _cache_put(group_key, qq, card)
        if card:
            names[qq] = card

    return names
