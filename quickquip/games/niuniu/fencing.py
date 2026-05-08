"""Fencing (击剑) battle mechanic for 牛牛大作战."""

from __future__ import annotations

import random
import time

from quickquip.games.config import NiuNiuConfig
from quickquip.games.niuniu.cooldown import fence_cd, fenced_cd
from quickquip.games.niuniu.events import (
    FENCE_BOT_DRAW,
    FENCE_BOT_LOSE,
    FENCE_BOT_WIN,
    FENCE_EVENTS,
    FENCE_LOSE_NEG,
    FENCE_LOSE_POS,
    FENCE_WIN_NEG,
    FENCE_WIN_POS,
    NO_NIUNIU_EVENTS,
    _normal_fence_event,
)
from quickquip.games.niuniu.gluing import _apply_decay
from quickquip.games.niuniu.store import NiuNiuStore


def _fence_win_prob(a: float, b: float) -> float:
    """Probability that player A wins (0.05–0.85). Based on length ratio."""
    if abs(a) < 0.001 or abs(b) < 0.001:
        return 0.5
    p = 0.85
    ratio = max(abs(a), abs(b)) / min(abs(a), abs(b))
    reduction = p * 0.1 * (ratio - 1)
    p = p - reduction
    if a < 0:
        p = 1.0 - p
    return max(0.05, min(p, 0.85))


def _fence_winner_is_role(
    i_win: bool, my_len: float, oppo_len: float, role: str, cfg: NiuNiuConfig
) -> bool:
    """Check if the winning player has the required role.

    *role*: "niutouren" (positive length >= dominate_threshold)
            "succubus"  (negative length, abs >= devour_threshold)
    """
    winner_len = my_len if i_win else oppo_len
    if role == "niutouren":
        return winner_len >= cfg.fence_dominate_threshold
    if role == "succubus":
        return winner_len < 0 and abs(winner_len) >= cfg.fence_devour_threshold
    return False


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
    store: NiuNiuStore, my_uid: str, my_len: float, oppo_uid: str
) -> str:
    """Handle fencing when the target has no niuniu registered."""
    chosen = random.choices(
        NO_NIUNIU_EVENTS, weights=[e["weight"] for e in NO_NIUNIU_EVENTS], k=1
    )[0]

    if chosen["name"] == "reject":
        return random.choice(chosen["msg"])
    elif chosen["name"] == "force_register":
        oppo_len = store.register(oppo_uid)
        prefix = random.choice(chosen["msg"]).format(oppo_len=oppo_len)
        result = fencing(store, my_uid, oppo_uid)
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
    store: NiuNiuStore, my_uid: str, oppo_uid: str, *, oppo_is_bot: bool = False
) -> str:
    """Execute a fencing battle. Returns result message."""
    my_len = store.get_length(my_uid)
    if my_len is None:
        return "你还没有牛牛呢！请先发送 注册牛牛"

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
            return _fence_no_target(store, my_uid, my_len, oppo_uid)

    origin_my = my_len
    origin_oppo = oppo_len
    cfg = store.config

    # Win probability
    win_prob = _fence_win_prob(my_len, oppo_len)
    fence_luck = store.get_fence_luck(my_uid)
    win_prob = min(0.95, max(0.05, win_prob + (fence_luck - 1.0) * 0.1))
    i_win = random.random() < win_prob

    # Weighted event selection
    chosen = random.choices(
        FENCE_EVENTS, weights=[e["weight"] for e in FENCE_EVENTS], k=1
    )[0]

    # Eligibility guards (pre-reversal): ensure at least one player qualifies
    if chosen["name"] == "dominate":
        threshold = cfg.fence_dominate_threshold
        if my_len < threshold and oppo_len < threshold:
            chosen = _normal_fence_event()
    elif chosen["name"] == "succubus_devour":
        threshold = cfg.fence_devour_threshold
        qualifies = (my_len < 0 and abs(my_len) >= threshold) or (
            oppo_len < 0 and abs(oppo_len) >= threshold
        )
        if not qualifies:
            chosen = _normal_fence_event()

    # Apply reversal *before* role check so the actual winner is tested
    if chosen["name"] == "reversal":
        i_win = not i_win

    # Post-reversal role check: winner must have the role for special effects
    require_role = chosen.get("require_role")
    if require_role:
        if not _fence_winner_is_role(i_win, my_len, oppo_len, require_role, cfg):
            chosen = _normal_fence_event()

    if chosen["name"] == "slip":
        i_win = False

    # ── succubus devour ──────────────────────────────────────────────
    if chosen["name"] == "succubus_devour":
        steal = round(
            min(abs(my_len), abs(oppo_len)) * cfg.fence_devour_steal_ratio, 2
        )
        loss_val = round(steal * 1.5, 2)
        if i_win:
            my_len = round(my_len + steal, 2)
            if not oppo_is_bot:
                oppo_len = round(oppo_len - loss_val, 2)
        else:
            my_len = round(my_len - loss_val, 2)
            if not oppo_is_bot:
                oppo_len = round(oppo_len + steal, 2)
        my_len = round(_apply_decay(my_len, cfg), 2)
        if not oppo_is_bot:
            oppo_len = round(_apply_decay(oppo_len, cfg), 2)
        _commit_fence_result(
            store, my_uid, origin_my, my_len, oppo_uid, origin_oppo, oppo_len, oppo_is_bot, cfg
        )
        if oppo_is_bot:
            msgs = FENCE_BOT_WIN if i_win else FENCE_BOT_LOSE
        elif i_win:
            msgs = (chosen.get("win_neg") or FENCE_WIN_NEG) if my_len < 0 else (chosen.get("win_pos") or FENCE_WIN_POS)
        else:
            msgs = (chosen.get("devoured_neg") or FENCE_LOSE_NEG) if my_len < 0 else (chosen.get("devoured_pos") or FENCE_LOSE_POS)
        return random.choice(msgs).format(gain=steal, loss=loss_val, my_len=my_len)

    # ── dominate sever ───────────────────────────────────────────────
    # Attacker is 牛头人, wins → sever opponent
    if (
        chosen["name"] == "dominate"
        and i_win
        and random.random() < cfg.fence_dominate_sever_chance
    ):
        old_oppo = oppo_len
        if oppo_len > 0:
            sever_loss = round(oppo_len * 0.5, 2)
            oppo_len = round(oppo_len - sever_loss, 2)
        else:
            sever_loss = round(abs(oppo_len), 2)
            oppo_len = round(oppo_len * 2, 2)
        gain = round(sever_loss * 0.6, 2)
        my_len = round(my_len + gain, 2)
        my_len = round(_apply_decay(my_len, cfg), 2)
        if not oppo_is_bot:
            oppo_len = round(_apply_decay(oppo_len, cfg), 2)
        _commit_fence_result(
            store, my_uid, origin_my, my_len, oppo_uid, origin_oppo, oppo_len, oppo_is_bot, cfg
        )
        if old_oppo > 0:
            msgs = chosen.get("sever_pos", chosen.get("win_pos"))
        else:
            msgs = chosen.get("sever_neg", chosen.get("win_neg"))
        return random.choice(msgs).format(
            gain=gain, loss=sever_loss, old_oppo=old_oppo, new_oppo=oppo_len
        )

    # Defender is 牛头人, wins → sever attacker
    if (
        chosen["name"] == "dominate"
        and not i_win
        and not oppo_is_bot
        and random.random() < cfg.fence_dominate_sever_chance
    ):
        old_my = my_len
        if my_len > 0:
            sever_loss = round(my_len * 0.5, 2)
            my_len = round(my_len - sever_loss, 2)
        else:
            sever_loss = round(abs(my_len), 2)
            my_len = round(my_len * 2, 2)
        gain = round(sever_loss * 0.6, 2)
        oppo_len = round(oppo_len + gain, 2)
        my_len = round(_apply_decay(my_len, cfg), 2)
        oppo_len = round(_apply_decay(oppo_len, cfg), 2)
        _commit_fence_result(
            store, my_uid, origin_my, my_len, oppo_uid, origin_oppo, oppo_len, oppo_is_bot, cfg
        )
        if old_my > 0:
            msgs = chosen.get("severed_pos", chosen.get("lose_pos"))
        else:
            msgs = chosen.get("severed_neg", chosen.get("lose_neg"))
        return random.choice(msgs).format(
            gain=gain, loss=sever_loss, old_my=old_my, new_my=my_len, my_len=my_len
        )

    # ── damage calculation ───────────────────────────────────────────
    base_change = min(abs(my_len), abs(oppo_len)) * 0.1
    rd = abs(time.time() % 10 - 5) + random.uniform(0.13, 0.24) * base_change
    balance = max(0.3, 1 - abs(my_len - oppo_len) / 100)
    reduce_val = round(rd * 0.3 * balance, 2)

    # ── draw ─────────────────────────────────────────────────────────
    if chosen["name"] == "draw":
        reduce_val = round(
            random.uniform(cfg.fence_draw_min, cfg.fence_draw_max), 2
        )
        my_len = round(my_len - reduce_val, 2)
        my_len = round(_apply_decay(my_len, cfg), 2)
        if not oppo_is_bot:
            oppo_len = round(oppo_len - reduce_val, 2)
            oppo_len = round(_apply_decay(oppo_len, cfg), 2)
        _commit_fence_result(
            store,
            my_uid, origin_my, my_len,
            oppo_uid, origin_oppo, oppo_len, oppo_is_bot, cfg,
            action="fencing_draw", oppo_action="fencing_draw",
        )
        msgs = FENCE_BOT_DRAW if oppo_is_bot else chosen["msg"]
        return random.choice(msgs).format(loss=reduce_val, my_len=my_len)

    # ── apply event multiplier ───────────────────────────────────────
    multiplier = {
        "critical": cfg.fence_critical_multiplier,
        "glancing": cfg.fence_glancing_multiplier,
        "dominate": cfg.fence_dominate_multiplier,
    }.get(chosen["name"], 1.0)
    reduce_val = round(reduce_val * multiplier, 2)

    if i_win:
        my_len = round(my_len + reduce_val, 2)
        if not oppo_is_bot:
            oppo_len = round(oppo_len - 0.8 * reduce_val, 2)
    else:
        my_len = round(my_len - reduce_val, 2)
        if not oppo_is_bot:
            oppo_len = round(oppo_len + 0.8 * reduce_val, 2)

    my_len = round(_apply_decay(my_len, cfg), 2)
    if not oppo_is_bot:
        oppo_len = round(_apply_decay(oppo_len, cfg), 2)

    loss_val = round(0.8 * reduce_val, 2)

    # ── message selection ────────────────────────────────────────────
    if oppo_is_bot:
        msgs = FENCE_BOT_WIN if i_win else FENCE_BOT_LOSE
    elif i_win:
        if my_len < 0:
            msgs = chosen.get("win_neg") or FENCE_WIN_NEG
        else:
            msgs = chosen.get("win_pos") or FENCE_WIN_POS
    else:
        if my_len < 0:
            msgs = chosen.get("lose_neg") or FENCE_LOSE_NEG
        else:
            msgs = chosen.get("lose_pos") or FENCE_LOSE_POS
    msg = random.choice(msgs).format(
        gain=reduce_val, loss=loss_val, my_len=my_len
    )

    _commit_fence_result(
        store, my_uid, origin_my, my_len, oppo_uid, origin_oppo, oppo_len, oppo_is_bot, cfg
    )
    return msg
