"""游戏域统一标识符管理。

内部口径：QQ 号字符串是唯一用户标识，存储、经济与会话全部以它为主键，
本模块不做任何改写。

展示口径：所有群内可见的游戏文案（排行榜、对局播报、结算行）经
``display_name`` 渲染，降级链为

    群内 canonical_name → 全局 canonical_name → 群内 QQ 昵称 → QQ{号}

链条语义由 ``common.identity_sources`` 的快照承载：合并索引中群内条目
覆盖全局条目（``IdentityIndex.merge``），昵称取自该群活跃名片与签到
统计。新增游戏一律从本模块取名，禁止在文案里直接拼接 QQ 号。
"""
from __future__ import annotations

from collections.abc import Callable

from quickquip.common.identity_sources import IdentitySnapshot, identities


def display_name(
    group_id: str | None,
    uid: str,
    *,
    snapshot: IdentitySnapshot | None = None,
) -> str:
    """QQ 号 → 显示名。

    ``group_id`` 为空（如私聊里查全局榜）时只用全局索引，不叠加群内
    条目与群昵称。``snapshot`` 供批量渲染方复用同一次快照。
    """
    uid = str(uid)
    if snapshot is None:
        snapshot = identities.snapshot(str(group_id) if group_id else "")
    return snapshot.name(uid)


def display_resolver(group_id: str | None) -> Callable[[str], str]:
    """取一次群快照，返回批量渲染用的 uid → 显示名 callable。

    排行榜等一次渲染多条目时用它，保证整张榜单出自同一份身份快照。
    """
    snapshot = identities.snapshot(str(group_id) if group_id else "")

    def _resolve(uid: str) -> str:
        return snapshot.name(str(uid))

    return _resolve
