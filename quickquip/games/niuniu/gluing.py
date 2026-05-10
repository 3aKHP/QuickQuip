"""Gluing (打胶) game mechanic for 牛牛大作战."""

import math
import random

from quickquip.games.config import NiuNiuConfig
from quickquip.games.niuniu.cooldown import arrested_cd, glue_cd
from quickquip.games.niuniu.events import GLUE_EVENTS
from quickquip.games.niuniu.store import NiuNiuStore


def _glue_growth(origin: float, coefficient: float = 1.0, scale: float = 200.0) -> float:
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


def gluing(store: NiuNiuStore, uid: str) -> tuple[str, float]:
    """Perform a gluing operation. Returns (result_message, new_length)."""
    origin = store.get_length(uid)
    if origin is None:
        return "你还没有牛牛呢！请先发送 注册牛牛", 0.0

    # Arrested check
    remaining = arrested_cd.check(uid)
    if remaining > 0:
        return f"你还在小黑屋里！{int(remaining)}s 后才能打胶", origin

    # Weighted event selection
    names = [e["name"] for e in GLUE_EVENTS]
    weights = [e["weight"] for e in GLUE_EVENTS]
    chosen_name = random.choices(names, weights=weights, k=1)[0]
    event = next(e for e in GLUE_EVENTS if e["name"] == chosen_name)

    cfg = store.config

    if event["category"] == "growth":
        coeff = {
            "lucky_day": cfg.glue_lucky_coefficient,
            "special_boost": cfg.glue_special_coefficient,
        }.get(event["name"], 1.0)
        diff = _glue_growth(origin, coeff, cfg.glue_growth_scale)
        new_length = round(origin + diff, 2)
        if diff > 0 and "pos" in event:
            msg = random.choice(event["pos"]).format(diff=abs(diff))
        elif diff < 0 and "neg" in event:
            msg = random.choice(event["neg"]).format(diff=abs(diff))
        else:
            msg = random.choice(event.get("zero", ["什么也没有发生…"])).format(diff=0)
    elif event["category"] == "shrinkage":
        effect = (
            cfg.glue_nightmare_effect
            if event["name"] == "nightmare"
            else cfg.glue_shrinkage_effect
        )
        if origin >= 0:
            new_length = round(origin * effect, 2)
        else:
            new_length = round(origin / effect, 2)
        diff = round(new_length - origin, 2)
        if "neg" in event:
            msg = random.choice(event["neg"]).format(
                diff=abs(diff), new_length=new_length
            )
        else:
            msg = f"你的牛牛萎缩了 {abs(diff)} cm！当前 {new_length} cm"
    elif event["category"] == "arrested":
        ban_time = cfg.glue_arrested_duration
        arrested_cd.set(uid, ban_time)
        new_length = origin
        diff = 0.0
        msg = random.choice(event.get("pos", ["你被抓走了！"])).format(
            ban_time=ban_time
        )
    elif event["category"] == "mirror":
        if abs(origin) < 0.01:
            new_length = origin
            msg = "你的牛牛太短了，镜子也找不到它……什么也没发生"
        else:
            new_length = round(-origin, 2)
            msg = random.choice(event["pos"]).format(new_length=new_length)
    elif event["category"] == "jackpot":
        diff = round(
            random.uniform(cfg.glue_blessing_min, cfg.glue_blessing_max), 2
        )
        new_length = round(origin + diff, 2)
        msg = random.choice(event["pos"]).format(diff=diff)
    elif event["category"] == "gambler":
        diff = round(
            random.uniform(cfg.glue_gambler_min, cfg.glue_gambler_max), 2
        )
        if random.random() < 0.5:
            new_length = round(origin + diff, 2)
            msg = random.choice(event["pos"]).format(diff=diff)
        else:
            diff = round(-diff, 2)
            new_length = round(origin + diff, 2)
            msg = random.choice(event["neg"]).format(diff=abs(diff))
    elif event["category"] == "zen":
        diff = round(random.uniform(cfg.glue_zen_min, cfg.glue_zen_max), 2)
        new_length = round(origin + diff, 2)
        msg = random.choice(event["pos"]).format(diff=diff)
    elif event["category"] == "frenzy":
        diff = round(random.uniform(cfg.glue_frenzy_min, cfg.glue_frenzy_max), 2)
        new_length = round(origin + diff, 2)
        msg = random.choice(event["pos"]).format(diff=diff)
    else:
        diff = _glue_growth(origin, 1.0, cfg.glue_growth_scale)
        new_length = round(origin + diff, 2)
        msg = f"你的牛牛变化了 {abs(diff)} cm"

    # Apply daily luck (except for arrested and mirror)
    if event["category"] not in ("arrested", "mirror"):
        luck = store.get_glue_luck(uid)
        luck_diff = round((new_length - origin) * luck, 2)

        new_length = round(origin + luck_diff, 2)
        diff_abs = abs(luck_diff)

        # Rebuild message with luck-adjusted diff
        if event["category"] == "growth":
            if luck_diff > 0 and "pos" in event:
                msg = random.choice(event["pos"]).format(diff=diff_abs)
            elif luck_diff < 0 and "neg" in event:
                msg = random.choice(event["neg"]).format(diff=diff_abs)
        elif event["category"] == "shrinkage":
            if "neg" in event:
                msg = random.choice(event["neg"]).format(
                    diff=diff_abs, new_length=new_length
                )
            else:
                msg = f"你的牛牛萎缩了 {diff_abs} cm！当前 {new_length} cm"
        elif event["category"] in ("jackpot", "gambler", "zen", "frenzy"):
            if luck_diff > 0 and "pos" in event:
                msg = random.choice(event["pos"]).format(diff=diff_abs)
            elif luck_diff < 0 and "neg" in event:
                msg = random.choice(event["neg"]).format(diff=diff_abs)

    # Apply decay
    new_length = _apply_decay(new_length, store.config)
    store.update_length(uid, new_length)

    glue_cd.set(uid, store.config.glue_cooldown)

    store._add_record(uid, "gluing", origin, new_length)
    return msg, new_length
