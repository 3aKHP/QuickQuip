"""Gluing (打胶) game mechanic for 牛牛大作战."""

import random

from quickquip.games.niuniu.cooldown import arrested_cd, glue_cd
from quickquip.games.niuniu.dynamics import (  # noqa: F401 (re-exported for tests)
    _apply_decay,
    _glue_growth,
    glue_resolve,
)
from quickquip.games.niuniu.store import NiuNiuStore


def gluing(store: NiuNiuStore, uid: str, group_id: str) -> tuple[str, float]:
    """Perform a gluing operation. Returns (result_message, new_length)."""
    origin = store.get_length(uid)
    if origin is None:
        return "你还没有牛牛呢！请先发送 /注册牛牛", 0.0

    # Arrested check
    remaining = arrested_cd.check(uid)
    if remaining > 0:
        return f"你还在小黑屋里！{int(remaining)}s 后才能打胶", origin

    text = store.get_text(group_id)
    events = text.glue_events
    # Weighted event selection
    names = [e["name"] for e in events]
    weights = [e["weight"] for e in events]
    chosen_name = random.choices(names, weights=weights, k=1)[0]
    event = next(e for e in events if e["name"] == chosen_name)

    cfg = store.config
    # Fetch daily luck only when the event actually consumes it, so that
    # arrested/mirror/shrinkage events do not trigger a luck re-roll.
    if event["category"] not in ("arrested", "mirror", "shrinkage"):
        luck = store.get_glue_luck(uid)
    else:
        luck = 1.0

    out = glue_resolve(
        origin, luck, event, cfg,
        neg_shrink="sublinear",
        neg_shrink_depth=cfg.glue_neg_shrink_depth,
        luck_power=cfg.luck_power,
    )

    if out.arrested:
        arrested_cd.set(uid, out.ban_time)

    store.update_length(uid, out.new_length)
    glue_cd.set(uid, cfg.glue_cooldown)

    store._add_record(uid, "gluing", origin, out.new_length)
    return out.msg, out.new_length
