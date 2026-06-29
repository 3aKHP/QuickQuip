"""Pure numeric dynamics for 牛牛大作战 — extracted from gluing/fencing.

No IO, no cooldowns, no store. These helpers depend only on their arguments
and *random*, so they can be unit-tested in isolation and driven by the
offline simulation sandbox (dev/niuniu_sandbox) without a database or
NoneBot.

gluing.py / fencing.py re-export the legacy names to preserve the import
paths used by tests.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass

from quickquip.games.config import NiuNiuConfig
from quickquip.games.niuniu.text import NiuNiuText


def _glue_growth(origin: float, coefficient: float = 1.0) -> float:
    """Calculate growth/shrinkage delta — proportional to sqrt(|origin|).

    Sqrt scaling keeps the recurrence L_{n+1} = L_n + β·√L_n quadratic
    (not exponential) and gives a finite equilibrium L* = (δβ/r)² when
    combined with decay — the system self-regulates without hard caps.
    """
    prob = random.choice([-0.6, -0.5, -0.4, -0.2, 0, 0.2, 0.4, 0.5, 0.6])
    base = math.sqrt(abs(origin))
    return round(prob * 0.4 * base * coefficient, 2)


def _apply_decay(length: float, cfg: NiuNiuConfig) -> float:
    """Apply length decay using config values."""
    if length > 50:
        rate = cfg.decay_rate_high
    elif length < -50:
        rate = -cfg.decay_rate_high / 2
    else:
        rate = cfg.decay_rate_normal
    if length > 0:
        return max(0.0, length * (1 - rate))
    return length * (1 + rate * 0.8)


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


# ── gluing step (pure) ──────────────────────────────────────────────────────


@dataclass(slots=True)
class GlueOutcome:
    """Result of a single gluing step — pure data, no side effects.

    *new_length* is post-decay (what gets persisted); *msg* is built from the
    event templates using the pre-decay diff/new_length, matching the legacy
    ordering. *arrested* + *ban_time* signal the orchestrator to set the
    arrest cooldown.
    """

    new_length: float
    msg: str
    arrested: bool = False
    ban_time: int = 0


def glue_resolve(
    origin: float, luck: float, event: dict, cfg: NiuNiuConfig,
    *,
    neg_shrink: str = "multiply",
    neg_shrink_depth: float = 1.0,
    luck_power: float = 1.0,
) -> GlueOutcome:
    """Resolve one gluing event deterministically from inputs.

    Pure: no store, no cooldown, no message-side-effects beyond ``random``.
    *event* is the chosen event dict (from ``text.glue_events``); *luck* is
    the caller-supplied daily multiplier (1.0 for arrested/mirror).
    """
    category = event["category"]
    name = event["name"]

    if category == "growth":
        coeff = {
            "lucky_day": cfg.glue_lucky_coefficient,
            "special_boost": cfg.glue_special_coefficient,
        }.get(name, 1.0)
        diff = _glue_growth(origin, coeff)
        new_length = round(origin + diff, 2)
        if diff > 0 and "pos" in event:
            msg = random.choice(event["pos"]).format(diff=abs(diff))
        elif diff < 0 and "neg" in event:
            msg = random.choice(event["neg"]).format(diff=abs(diff))
        else:
            msg = random.choice(event.get("zero", ["什么也没有发生…"])).format(diff=0)
    elif category == "shrinkage":
        effect = (
            cfg.glue_nightmare_effect
            if name == "nightmare"
            else cfg.glue_shrinkage_effect
        )
        if origin >= 0:
            new_length = round(origin * effect, 2)
        elif neg_shrink == "sublinear":
            # 凹侧 sublinear 加深(取代乘性翻倍)：α=0.5 不发散,与 growth 的
            # √|origin| 扩散同构。depth 是单 scalar——nightmare 与 shrinkage
            # 在凹侧等价(intentional;正侧才用 effect 区分两者)。
            new_length = round(origin - neg_shrink_depth * math.sqrt(abs(origin)), 2)
        else:
            new_length = round(origin / effect, 2)
        diff = round(new_length - origin, 2)
        if "neg" in event:
            msg = random.choice(event["neg"]).format(
                diff=abs(diff), new_length=new_length
            )
        else:
            msg = f"你的牛牛萎缩了 {abs(diff)} cm！当前 {new_length} cm"
    elif category == "arrested":
        new_length = origin
        msg = random.choice(event.get("pos", ["你被抓走了！"])).format(
            ban_time=cfg.glue_arrested_duration
        )
    elif category == "mirror":
        if abs(origin) < 0.01:
            new_length = origin
            msg = "你的牛牛太短了，镜子也找不到它……什么也没发生"
        else:
            new_length = round(-origin, 2)
            msg = random.choice(event["pos"]).format(new_length=new_length)
    elif category == "jackpot":
        diff = round(random.uniform(cfg.glue_blessing_min, cfg.glue_blessing_max), 2)
        new_length = round(origin + diff, 2)
        msg = random.choice(event["pos"]).format(diff=diff)
    elif category == "gambler":
        diff = round(random.uniform(cfg.glue_gambler_min, cfg.glue_gambler_max), 2)
        if random.random() < 0.5:
            new_length = round(origin + diff, 2)
            msg = random.choice(event["pos"]).format(diff=diff)
        else:
            diff = round(-diff, 2)
            new_length = round(origin + diff, 2)
            msg = random.choice(event["neg"]).format(diff=abs(diff))
    elif category == "zen":
        diff = round(random.uniform(cfg.glue_zen_min, cfg.glue_zen_max), 2)
        new_length = round(origin + diff, 2)
        msg = random.choice(event["pos"]).format(diff=diff)
    elif category == "frenzy":
        diff = round(random.uniform(cfg.glue_frenzy_min, cfg.glue_frenzy_max), 2)
        new_length = round(origin + diff, 2)
        msg = random.choice(event["pos"]).format(diff=diff)
    else:
        diff = _glue_growth(origin, 1.0)
        new_length = round(origin + diff, 2)
        msg = f"你的牛牛变化了 {abs(diff)} cm"

    # Apply daily luck (except arrested/mirror/shrinkage). shrinkage is a fixed
    # penalty — luck must NOT amplify it, or "神运" would worsen the punishment.
    if category not in ("arrested", "mirror", "shrinkage"):
        mf = luck ** luck_power
        luck_diff = round((new_length - origin) * mf, 2)
        new_length = round(origin + luck_diff, 2)
        diff_abs = abs(luck_diff)

        # Rebuild message with luck-adjusted diff
        if category == "growth":
            if luck_diff > 0 and "pos" in event:
                msg = random.choice(event["pos"]).format(diff=diff_abs)
            elif luck_diff < 0 and "neg" in event:
                msg = random.choice(event["neg"]).format(diff=diff_abs)
        elif category in ("jackpot", "gambler", "zen", "frenzy"):
            if luck_diff > 0 and "pos" in event:
                msg = random.choice(event["pos"]).format(diff=diff_abs)
            elif luck_diff < 0 and "neg" in event:
                msg = random.choice(event["neg"]).format(diff=diff_abs)

    # Apply decay
    new_length = _apply_decay(new_length, cfg)

    return GlueOutcome(
        new_length=new_length,
        msg=msg,
        arrested=(category == "arrested"),
        ban_time=cfg.glue_arrested_duration if category == "arrested" else 0,
    )


# ── fencing step (pure) ─────────────────────────────────────────────────────


@dataclass(slots=True)
class FenceOutcome:
    """Result of one fencing duel — pure data, no side effects.

    The orchestrator persists *my_new* / *oppo_new*, writes records tagged
    with *action* / *oppo_action*, and sets cooldowns.
    """

    my_new: float
    oppo_new: float
    msg: str
    action: str = "fencing"
    oppo_action: str = "fenced"


def _normal_event(text: NiuNiuText) -> dict:
    """Return the 'normal' fencing event dict from *text*."""
    for e in text.fence_events:
        if e["name"] == "normal":
            return e
    return {"name": "normal", "weight": 50}


def fence_resolve(
    my_len: float,
    oppo_len: float,
    my_luck: float,
    oppo_luck_provider: Callable[[], float],
    text: NiuNiuText,
    cfg: NiuNiuConfig,
    oppo_is_bot: bool,
) -> FenceOutcome:
    """Resolve one fencing duel deterministically from inputs.

    Pure: no store, no cooldown. *my_luck* is the attacker's daily fence luck
    (caller-supplied); *oppo_luck_provider* is called lazily only when the
    defender-sever branch fires, preserving the legacy side-effect timing.
    """
    win_prob = _fence_win_prob(my_len, oppo_len)
    win_prob = min(0.95, max(0.05, win_prob + (my_luck - 1.0) * 0.1))
    i_win = random.random() < win_prob

    # Weighted event selection
    fence_events = text.fence_events
    chosen = random.choices(
        fence_events, weights=[e["weight"] for e in fence_events], k=1
    )[0]

    # Eligibility guards (pre-reversal): ensure at least one player qualifies
    if chosen["name"] == "dominate":
        threshold = cfg.fence_dominate_threshold
        if my_len < threshold and oppo_len < threshold:
            chosen = _normal_event(text)
    elif chosen["name"] == "succubus_devour":
        threshold = cfg.fence_devour_threshold
        qualifies = (my_len < 0 and abs(my_len) >= threshold) or (
            oppo_len < 0 and abs(oppo_len) >= threshold
        )
        if not qualifies:
            chosen = _normal_event(text)

    # Apply reversal *before* role check so the actual winner is tested
    if chosen["name"] == "reversal":
        i_win = not i_win

    # Post-reversal role check: winner must have the role for special effects
    require_role = chosen.get("require_role")
    if require_role:
        if not _fence_winner_is_role(i_win, my_len, oppo_len, require_role, cfg):
            chosen = _normal_event(text)

    if chosen["name"] == "slip":
        i_win = False

    # ── succubus devour ──────────────────────────────────────────────
    if chosen["name"] == "succubus_devour":
        steal = round(
            min(abs(my_len), abs(oppo_len)) * cfg.fence_devour_steal_ratio * my_luck, 2
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
        if oppo_is_bot:
            msgs = text.fence_bot["win"] if i_win else text.fence_bot["lose"]
        elif i_win:
            msgs = (chosen.get("win_neg") or text.fence_shared["win_neg"]) if my_len < 0 else (chosen.get("win_pos") or text.fence_shared["win_pos"])
        else:
            msgs = (chosen.get("devoured_neg") or text.fence_shared["lose_neg"]) if my_len < 0 else (chosen.get("devoured_pos") or text.fence_shared["lose_pos"])
        msg = random.choice(msgs).format(gain=steal, loss=loss_val, my_len=my_len)
        return FenceOutcome(my_new=my_len, oppo_new=oppo_len, msg=msg)

    # ── dominate sever ───────────────────────────────────────────────
    # Attacker is 牛头人, wins → sever opponent
    if (
        chosen["name"] == "dominate"
        and i_win
        and random.random() < cfg.fence_dominate_sever_chance
    ):
        old_oppo = oppo_len
        if oppo_len > 0:
            sever_ratio = min(0.95, 0.5 * my_luck)
            sever_loss = round(oppo_len * sever_ratio, 2)
            oppo_len = round(oppo_len - sever_loss, 2)
        else:
            deepen_ratio = min(3.0, 1.0 * my_luck)
            sever_loss = round(abs(oppo_len) * deepen_ratio, 2)
            oppo_len = round(oppo_len - sever_loss, 2)
        gain = round(sever_loss * 0.6, 2)
        my_len = round(my_len + gain, 2)
        my_len = round(_apply_decay(my_len, cfg), 2)
        if not oppo_is_bot:
            oppo_len = round(_apply_decay(oppo_len, cfg), 2)
        if old_oppo > 0:
            msgs = chosen.get("sever_pos", chosen.get("win_pos"))
        else:
            msgs = chosen.get("sever_neg", chosen.get("win_neg"))
        msg = random.choice(msgs).format(
            gain=gain, loss=sever_loss, old_oppo=old_oppo, new_oppo=oppo_len
        )
        return FenceOutcome(my_new=my_len, oppo_new=oppo_len, msg=msg)

    # Defender is 牛头人, wins → sever attacker
    if (
        chosen["name"] == "dominate"
        and not i_win
        and not oppo_is_bot
        and random.random() < cfg.fence_dominate_sever_chance
    ):
        old_my = my_len
        defender_luck = oppo_luck_provider()
        if my_len > 0:
            sever_ratio = min(0.95, 0.5 * defender_luck)
            sever_loss = round(my_len * sever_ratio, 2)
            my_len = round(my_len - sever_loss, 2)
        else:
            deepen_ratio = min(3.0, 1.0 * defender_luck)
            sever_loss = round(abs(my_len) * deepen_ratio, 2)
            my_len = round(my_len - sever_loss, 2)
        gain = round(sever_loss * 0.6, 2)
        oppo_len = round(oppo_len + gain, 2)
        my_len = round(_apply_decay(my_len, cfg), 2)
        oppo_len = round(_apply_decay(oppo_len, cfg), 2)
        if old_my > 0:
            msgs = chosen.get("severed_pos", chosen.get("lose_pos"))
        else:
            msgs = chosen.get("severed_neg", chosen.get("lose_neg"))
        msg = random.choice(msgs).format(
            gain=gain, loss=sever_loss, old_my=old_my, new_my=my_len, my_len=my_len
        )
        return FenceOutcome(my_new=my_len, oppo_new=oppo_len, msg=msg)

    # ── damage calculation ───────────────────────────────────────────
    base = min(abs(my_len), abs(oppo_len))
    ratio = base / max(abs(my_len), abs(oppo_len), 0.01)
    balance = max(0.3, ratio)
    reduce_val = round(base * random.uniform(0.04, 0.06) * balance, 2)

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
        msgs = text.fence_bot["draw"] if oppo_is_bot else chosen["msg"]
        msg = random.choice(msgs).format(loss=reduce_val, my_len=my_len)
        return FenceOutcome(
            my_new=my_len, oppo_new=oppo_len, msg=msg,
            action="fencing_draw", oppo_action="fencing_draw",
        )

    # ── apply event multiplier ───────────────────────────────────────
    multiplier = {
        "critical": cfg.fence_critical_multiplier,
        "glancing": cfg.fence_glancing_multiplier,
        "dominate": cfg.fence_dominate_multiplier,
    }.get(chosen["name"], 1.0)
    reduce_val = round(reduce_val * multiplier * my_luck, 2)

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
        msgs = text.fence_bot["win"] if i_win else text.fence_bot["lose"]
    elif i_win:
        if my_len < 0:
            msgs = chosen.get("win_neg") or text.fence_shared["win_neg"]
        else:
            msgs = chosen.get("win_pos") or text.fence_shared["win_pos"]
    else:
        if my_len < 0:
            msgs = chosen.get("lose_neg") or text.fence_shared["lose_neg"]
        else:
            msgs = chosen.get("lose_pos") or text.fence_shared["lose_pos"]
    msg = random.choice(msgs).format(gain=reduce_val, loss=loss_val, my_len=my_len)

    return FenceOutcome(my_new=my_len, oppo_new=oppo_len, msg=msg)


def fence_resolve_zerohsum(
    my_len: float,
    oppo_len: float,
    my_luck: float,
    oppo_luck_provider: Callable[[], float],
    text: NiuNiuText,
    cfg: NiuNiuConfig,
    oppo_is_bot: bool,
    *,
    luck_power: float = 1.0,
) -> FenceOutcome:
    """Strict zero-sum fencing: Δmy + Δoppo == 0 exactly.

    Winner gains *stake*, loser loses the same stake. No decay, no net
    creation/destruction — the pair's total length is invariant, so the whole
    population's Σlength stays constant under pure fencing (verifiable in the
    sandbox). Single-side change can be huge (uncapped) because stake may
    scale with length and luck, but it is always mirrored.

    Win determination and eligibility guards mirror the legacy fence_resolve;
    only the transfer is made symmetric and decay is dropped. dominate sever
    and succubus devour are full transfers (legacy 0.6× / 1.5× broke
    conservation). NB: *luck* still scales stake and win_prob here — tightening
    that is deferred to the gluing/luck redesign. NB: draw is an intentional
    non-zero-sum exception (两败俱伤, anti-inflation — both sides lose,
    offsetting gluing's positive Σ drift).
    """
    # ── win determination (legacy) ───────────────────────────────────
    win_prob = _fence_win_prob(my_len, oppo_len)
    win_prob = min(0.95, max(0.05, win_prob + (my_luck - 1.0) * 0.1))
    i_win = random.random() < win_prob

    fence_events = text.fence_events
    chosen = random.choices(
        fence_events, weights=[e["weight"] for e in fence_events], k=1
    )[0]

    if chosen["name"] == "dominate":
        if my_len < cfg.fence_dominate_threshold and oppo_len < cfg.fence_dominate_threshold:
            chosen = _normal_event(text)
    elif chosen["name"] == "succubus_devour":
        threshold = cfg.fence_devour_threshold
        qualifies = (my_len < 0 and abs(my_len) >= threshold) or (
            oppo_len < 0 and abs(oppo_len) >= threshold
        )
        if not qualifies:
            chosen = _normal_event(text)

    if chosen["name"] == "reversal":
        i_win = not i_win

    require_role = chosen.get("require_role")
    if require_role and not _fence_winner_is_role(i_win, my_len, oppo_len, require_role, cfg):
        chosen = _normal_event(text)

    if chosen["name"] == "slip":
        i_win = False

    # ── zero-sum stake (≥ 0) ─────────────────────────────────────────
    # luck is compressed by a sublinear power before scaling stake: median
    # luck (1.0) is unchanged (1**α == 1, so fencing stays punchy vs gluing)
    # while extreme luck is tamed. luck_power=1.0 reproduces raw multiply.
    mf = my_luck ** luck_power
    old_my, old_oppo = my_len, oppo_len
    msg_branch = "normal"

    if chosen["name"] == "succubus_devour":
        stake = round(
            min(abs(my_len), abs(oppo_len)) * cfg.fence_devour_steal_ratio * mf, 2
        )
        msg_branch = "succubus"
    elif chosen["name"] == "dominate":
        sever = random.random() < cfg.fence_dominate_sever_chance
        if sever and i_win:
            # attacker severs opponent (allowed vs bot too — attacker gains from phantom)
            stake = round(abs(oppo_len) * min(0.95, 0.5 * mf), 2)
            msg_branch = "dominate_sever"
        elif sever and not oppo_is_bot:
            # defender severs attacker — guard vs bot (legacy: bot phantom can't sever)
            df = oppo_luck_provider() ** luck_power
            stake = round(abs(my_len) * min(0.95, 0.5 * df), 2)
            msg_branch = "dominate_sever"
        else:
            base = min(abs(my_len), abs(oppo_len))
            balance = max(0.3, base / max(abs(my_len), abs(oppo_len), 0.01))
            stake = round(
                base * random.uniform(0.04, 0.06) * balance
                * cfg.fence_dominate_multiplier * mf, 2
            )
    elif chosen["name"] == "draw":
        # 两败俱伤(有意破例,非零和):双方各损,用于略微抵消打胶正期望的 Σ 通胀。
        # fence_bot 的 draw 文案待后续单独处理。
        reduce_val = round(random.uniform(cfg.fence_draw_min, cfg.fence_draw_max), 2)
        my_len = round(my_len - reduce_val, 2)
        oppo_len = round(oppo_len - reduce_val, 2)
        msgs = text.fence_bot["draw"] if oppo_is_bot else chosen["msg"]
        msg = random.choice(msgs).format(loss=reduce_val, my_len=my_len)
        return FenceOutcome(
            my_new=my_len, oppo_new=oppo_len, msg=msg,
            action="fencing_draw", oppo_action="fencing_draw",
        )
    else:
        base = min(abs(my_len), abs(oppo_len))
        balance = max(0.3, base / max(abs(my_len), abs(oppo_len), 0.01))
        multiplier = {
            "critical": cfg.fence_critical_multiplier,
            "glancing": cfg.fence_glancing_multiplier,
        }.get(chosen["name"], 1.0)
        stake = round(
            base * random.uniform(0.04, 0.06) * balance * multiplier * mf, 2
        )

    # ── symmetric zero-sum transfer, no decay ────────────────────────
    if i_win:
        my_len = round(my_len + stake, 2)
        oppo_len = round(oppo_len - stake, 2)
    else:
        my_len = round(my_len - stake, 2)
        oppo_len = round(oppo_len + stake, 2)
    loss_val = stake  # zero-sum: gain == loss == stake

    # ── per-event message selection (mirrors fence_resolve) ──────────
    if msg_branch == "succubus":
        if oppo_is_bot:
            msgs = text.fence_bot["win"] if i_win else text.fence_bot["lose"]
        elif i_win:
            msgs = (chosen.get("win_neg") or text.fence_shared["win_neg"]) if my_len < 0 else (chosen.get("win_pos") or text.fence_shared["win_pos"])
        else:
            msgs = (chosen.get("devoured_neg") or text.fence_shared["lose_neg"]) if my_len < 0 else (chosen.get("devoured_pos") or text.fence_shared["lose_pos"])
        msg = random.choice(msgs).format(gain=stake, loss=loss_val, my_len=my_len)
    elif msg_branch == "dominate_sever":
        if i_win:
            msgs = chosen.get("sever_pos", chosen.get("win_pos")) if old_oppo > 0 else chosen.get("sever_neg", chosen.get("win_neg"))
        else:
            msgs = chosen.get("severed_pos", chosen.get("lose_pos")) if old_my > 0 else chosen.get("severed_neg", chosen.get("lose_neg"))
        msg = random.choice(msgs).format(
            gain=stake, loss=loss_val, my_len=my_len,
            old_oppo=old_oppo, new_oppo=oppo_len, old_my=old_my, new_my=my_len,
        )
    else:  # normal / critical / glancing / reversal / slip
        if oppo_is_bot:
            msgs = text.fence_bot["win"] if i_win else text.fence_bot["lose"]
        elif i_win:
            msgs = (chosen.get("win_neg") or text.fence_shared["win_neg"]) if my_len < 0 else (chosen.get("win_pos") or text.fence_shared["win_pos"])
        else:
            msgs = (chosen.get("lose_neg") or text.fence_shared["lose_neg"]) if my_len < 0 else (chosen.get("lose_pos") or text.fence_shared["lose_pos"])
        msg = random.choice(msgs).format(gain=stake, loss=loss_val, my_len=my_len)

    return FenceOutcome(my_new=my_len, oppo_new=oppo_len, msg=msg)


def fence_resolve_bot(
    my_len: float, my_luck: float, text: NiuNiuText,
    *, luck_power: float = 1.0,
) -> FenceOutcome:
    """Bot 击剑: 纯娱乐, E[Δmy] = 0。

    win_prob 固定 0.5(luck 不进胜率 → 期望严格 0)。luck 只放大 stake(方差)。
    stake ∝ √max(my,0)(sublinear, my≥0 有效; my<0 由编排层拒绝)。bot 是简化
    靶子, 只 win/lose, 不走 sever/devour/draw(fence_bot draw 文案待后续)。
    """
    mf = my_luck ** luck_power
    stake = round(math.sqrt(max(my_len, 0.0)) * random.uniform(0.4, 0.6) * mf, 2)
    if random.random() < 0.5:
        my_len = round(my_len + stake, 2)
        msg = random.choice(text.fence_bot["win"]).format(gain=stake, my_len=my_len)
    else:
        my_len = round(my_len - stake, 2)
        msg = random.choice(text.fence_bot["lose"]).format(loss=stake, my_len=my_len)
    return FenceOutcome(my_new=my_len, oppo_new=0.0, msg=msg)
