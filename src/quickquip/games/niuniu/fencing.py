"""Fencing (击剑) battle mechanic for 牛牛大作战."""

from __future__ import annotations

import random

from quickquip.games.config import NiuNiuConfig
from quickquip.games.niuniu.cooldown import fence_cd, fenced_cd
from quickquip.games.niuniu.dynamics import (
    _apply_decay,
    fence_resolve_bot,
    fence_resolve_zerohsum,
)
from quickquip.games.niuniu.dynamics import (  # noqa: F401 (re-exported for tests)
    _fence_win_prob,
    _fence_winner_is_role,
)
from quickquip.games.niuniu.store import NiuNiuStore


def _commit_fence_result(
    store: NiuNiuStore,
    my_uid: str,
    my_old: float,
    my_new: float,
    oppo_uid: str,
    oppo_old: float,
    oppo_new: float,
    oppo_is_bot: bool,
    cfg: NiuNiuConfig,
    *,
    action: str = "fencing",
    oppo_action: str = "fenced",
) -> None:
    """Persist both players' new lengths, records, and cooldowns."""
    store.update_length(my_uid, my_new)
    store._add_record(my_uid, action, my_old, my_new)
    if not oppo_is_bot:
        store.update_length(oppo_uid, oppo_new)
        store._add_record(oppo_uid, oppo_action, oppo_old, oppo_new)
        fenced_cd.set(oppo_uid, cfg.fenced_protection)
    fence_cd.set(my_uid, cfg.fence_cooldown)


def _fence_no_target(
    store: NiuNiuStore, my_uid: str, my_len: float, oppo_uid: str, group_id: str
) -> str:
    """Handle fencing when the target has no niuniu registered."""
    text = store.get_text(group_id)
    events = text.fence_no_target
    chosen = random.choices(
        events, weights=[e["weight"] for e in events], k=1
    )[0]

    if chosen["name"] == "reject":
        return random.choice(chosen["msg"])
    elif chosen["name"] == "force_register":
        oppo_len = store.register(oppo_uid)
        prefix = random.choice(chosen["msg"]).format(oppo_len=oppo_len)
        result = fencing(store, my_uid, oppo_uid, group_id=group_id)
        return prefix + "\n" + result
    elif chosen["name"] == "self_hurt":
        loss = round(
            random.uniform(
                store.config.fence_self_hurt_min, store.config.fence_self_hurt_max
            ),
            2,
        )
        new_len = round(my_len - loss, 2)
        new_len = _apply_decay(new_len, store.config)
        store.update_length(my_uid, round(new_len, 2))
        store._add_record(my_uid, "fencing_self_hurt", my_len, new_len)
        fence_cd.set(my_uid, store.config.fence_cooldown)
        return random.choice(chosen["msg"]).format(loss=loss)
    return "出了一点问题……"


def fencing(
    store: NiuNiuStore, my_uid: str, oppo_uid: str, *, oppo_is_bot: bool = False,
    group_id: str = "",
) -> str:
    """Execute a fencing battle. Returns result message."""
    my_len = store.get_length(my_uid)
    if my_len is None:
        return "你还没有牛牛呢！请先发送 /注册牛牛"

    text = store.get_text(group_id)
    oppo_len = store.get_length(oppo_uid)

    # Target has no niuniu — bot gets a phantom, others trigger events
    if oppo_len is None:
        if oppo_is_bot:
            oppo_len = round(
                random.uniform(
                    store.config.fence_bot_phantom_min,
                    store.config.fence_bot_phantom_max,
                ),
                2,
            )
        else:
            return _fence_no_target(store, my_uid, my_len, oppo_uid, group_id)

    origin_my = my_len
    origin_oppo = oppo_len
    cfg = store.config
    my_luck = store.get_fence_luck(my_uid)

    if oppo_is_bot:
        if my_len < 0:
            fence_cd.set(my_uid, cfg.fence_cooldown)
            return "深渊魅魔形态下无法与机器人击剑……"
        out = fence_resolve_bot(
            my_len, my_luck, text,
            luck_power=cfg.luck_power, mf_cap=cfg.fence_stake_mf_cap,
        )
    else:
        out = fence_resolve_zerohsum(
            my_len,
            oppo_len,
            my_luck,
            lambda: store.get_fence_luck(oppo_uid),
            text,
            cfg,
            oppo_is_bot=False,
            luck_power=cfg.luck_power,
        )

    _commit_fence_result(
        store, my_uid, origin_my, out.my_new, oppo_uid, origin_oppo, out.oppo_new,
        oppo_is_bot, cfg, action=out.action, oppo_action=out.oppo_action,
    )
    return out.msg
