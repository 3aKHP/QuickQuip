"""「xxx了」公式 prompting 与 parsing 的单元测试。"""

from __future__ import annotations

from quickquip.sts.formulas.card_le.parsing import extract_card_le_name
from quickquip.sts.formulas.card_le.prompting import build_nearest_prompt, build_turmfluch_prompt


def test_turmfluch_prompt_contains_name_list_and_input():
    pack = build_turmfluch_prompt(prompt="今天好倒霉")
    assert "疑虑" in pack.system_prompt  # 清单注入
    assert "今天好倒霉" in pack.user_prompt


def test_turmfluch_prompt_includes_quote_and_images():
    pack = build_turmfluch_prompt(
        prompt="",
        image_urls=["http://example.com/a.png"],
        quoted_text="引用原文",
        quoted_image_urls=["http://example.com/b.png"],
        quoted_sender_name="张三",
    )
    assert "引用（张三）" in pack.user_prompt
    assert "引用原文" in pack.user_prompt


def test_nearest_prompt_mentions_captured():
    pack = build_nearest_prompt(captured="破防")
    assert "破防" in pack.user_prompt
    assert "疑虑" in pack.system_prompt


def test_extract_valid_name():
    assert extract_card_le_name("疑虑了") == "疑虑"
    assert extract_card_le_name("狂宴了") == "狂宴"


def test_extract_strips_quotes():
    assert extract_card_le_name("「疑虑了」") == "疑虑"
    assert extract_card_le_name("“狂宴了”") == "狂宴"


def test_extract_scans_embedded_name():
    # 模型偶发附带多余文字，兜底扫描清单命中
    assert extract_card_le_name("我觉得是计划妥当了") == "计划妥当"


def test_extract_rejects_excluded_and_unknown():
    assert extract_card_le_name("打击了") is None  # 标准打防被排除
    assert extract_card_le_name("防御了") is None
    assert extract_card_le_name("不存在的名字了") is None
    assert extract_card_le_name("乱七八糟") is None
