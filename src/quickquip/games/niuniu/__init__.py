"""牛牛大作战 — persistent RPG with gluing / fencing mechanics."""

from quickquip.games.niuniu.cooldown import (
    CooldownTracker,
    arrested_cd,
    fence_cd,
    fenced_cd,
    glue_cd,
)
from quickquip.games.niuniu.events import get_comment
from quickquip.games.niuniu.fencing import fencing
from quickquip.games.niuniu.gluing import _apply_decay, gluing
from quickquip.games.niuniu.store import NiuNiuStore
from quickquip.games.niuniu.text import NiuNiuText, default_text, load_niuniu_text

__all__ = [
    "CooldownTracker",
    "NiuNiuStore",
    "NiuNiuText",
    "_apply_decay",
    "arrested_cd",
    "default_text",
    "fence_cd",
    "fenced_cd",
    "fencing",
    "get_comment",
    "glue_cd",
    "gluing",
    "load_niuniu_text",
]
