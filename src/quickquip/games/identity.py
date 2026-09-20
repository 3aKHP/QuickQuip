"""游戏域统一标识符管理。

内部口径：QQ 号字符串是唯一用户标识，存储、经济与会话全部以它为主键，
本模块不做任何改写。

展示口径：所有群内可见的游戏文案（排行榜、对局播报、结算行）经
``display_name`` / ``display_names`` 渲染，降级链为

    群内 canonical_name → 全局 canonical_name → 群内 QQ 昵称 → QQ{号}

链条语义由 ``common.identity_sources`` 的快照承载：合并索引中群内条目
覆盖全局条目（``IdentityIndex.merge``），昵称取自该群活跃名片与签到
统计。两级 canonical 的取值继承快照层的占位跳过语义：值本身是 QQ 数字
串或「未知」时按未登记处理，直接落到昵称级。新增游戏一律从本模块取
名，禁止在文案里直接拼接 QQ 号。
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable

from quickquip.common.identity_sources import identities


def _snapshot_for(group_id: str | None):
    """群上下文归一化的唯一入口：空（如私聊查全局榜）走纯全局 scope。"""
    return identities.snapshot(str(group_id) if group_id else "")


def display_name(group_id: str | None, uid: str) -> str:
    """QQ 号 → 显示名（单条渲染）。"""
    return _snapshot_for(group_id).name(uid)


def display_resolver(group_id: str | None) -> Callable[[str], str]:
    """取一次群快照，返回批量渲染用的 uid → 显示名 callable。

    排行榜等一次渲染多条目时用它，保证整张榜单出自同一份身份快照。
    """
    snapshot = _snapshot_for(group_id)

    def _resolve(uid: str) -> str:
        return snapshot.name(uid)

    return _resolve


def display_names(group_id: str | None, uids: Iterable[str]) -> dict[str, str]:
    """同帧批量渲染 + 同名消歧。

    同一条消息里要同时展示多个玩家（发牌名单、结算行、对决播报）时用
    它：一次快照保证同帧一致；显示名撞车（一人多号或同名名片）时追加
    ``（QQ{号}）`` 后缀保住归属可判——旧 ``QQ:{uid}`` 文案天然唯一，
    显示名化后由这层补回。
    """
    uid_list = [str(uid) for uid in uids]
    snapshot = _snapshot_for(group_id)
    names = {uid: snapshot.name(uid) for uid in uid_list}
    counts = Counter(names.values())
    return {
        uid: f"{name}（QQ{uid}）" if counts[name] > 1 else name
        for uid, name in names.items()
    }
