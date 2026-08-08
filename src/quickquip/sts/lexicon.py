"""杀戮尖塔卡牌/遗物中文词表：加载、排除与查询。

词表由 ``scripts/refresh_sts_lexicon.py`` 从 nkhoit/spire-archive 生成（两代
cards/relics 与简中本地化 join 后按中文名跨代去重）。本模块经
``importlib.resources`` 加载 vendored 文件，套用 ``EXCLUDED_NAMES`` 得到活跃集合，
供「xxx了」公式的命中判定与 LLM 候选约束使用。
"""

from __future__ import annotations

import json
import logging
from importlib.resources import files

from quickquip.sts.config import EXCLUDED_NAMES

logger = logging.getLogger(__name__)


def _load() -> tuple[dict, dict]:
    """加载 vendored 词表，返回 (meta, names)。加载失败返回空 dict 并记日志。"""
    try:
        raw = json.loads(
            files("quickquip.sts").joinpath("sts_lexicon.json").read_text(encoding="utf-8")
        )
    except Exception:
        logger.exception("STS 词表加载失败，STS 公式化功能将不可用")
        return {}, {}
    return raw.get("_meta", {}), raw.get("names", {})


_META, _ALL_NAMES = _load()

# 活跃集合 = 完整词表 - 排除项（标准打防牌等）
NAMES: frozenset[str] = frozenset(_ALL_NAMES.keys() - set(EXCLUDED_NAMES))

_excluded_hits = sorted(_ALL_NAMES.keys() & set(EXCLUDED_NAMES))
if _excluded_hits:
    logger.info("STS 词表已排除 %d 项：%s", len(_excluded_hits), "、".join(_excluded_hits))


def is_card_name(name: str) -> bool:
    """``name`` 是否为活跃卡牌/遗物名（已排除标准打防牌等）。"""
    return name in NAMES


def get(name: str) -> dict | None:
    """取 ``name`` 的元数据（games/kind/en/ids/meta）；不存在或被排除仍返回原始记录。"""
    return _ALL_NAMES.get(name)


def meta() -> dict:
    """词表来源元信息（source/source_sha/sts2_version/count 等）。"""
    return dict(_META)
