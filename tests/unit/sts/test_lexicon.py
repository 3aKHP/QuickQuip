"""``quickquip.sts.lexicon`` 的单元测试。"""

from __future__ import annotations

import quickquip.sts.lexicon as lexicon


def test_active_names_nonempty():
    assert isinstance(lexicon.NAMES, frozenset)
    assert len(lexicon.NAMES) > 1000  # 两代合计应有千余条


def test_known_active_names():
    # 用户给出的示例 + 子串牌，都应在活跃集合里
    for name in ("疑虑", "狂宴", "计划妥当", "完美打击", "究极防御", "燃烧之血"):
        assert lexicon.is_card_name(name), f"{name} 应在活跃词表中"


def test_excluded_strike_defend():
    # 标准打防牌被排除
    assert not lexicon.is_card_name("打击")
    assert not lexicon.is_card_name("防御")
    # 但它们仍在原始记录里（get 能查到），只是不进活跃集合
    assert lexicon.get("打击") is not None
    assert lexicon.get("防御") is not None


def test_non_names():
    assert not lexicon.is_card_name("不是一张卡")
    assert not lexicon.is_card_name("")
    assert not lexicon.is_card_name("破防")


def test_get_returns_metadata():
    doubt = lexicon.get("疑虑")
    assert doubt is not None
    assert "Doubt" in doubt["en"]
    assert doubt["meta"]["type"] == "Curse"


def test_meta_has_source():
    m = lexicon.meta()
    assert "source_sha" in m
    assert m.get("count", 0) > 1000
