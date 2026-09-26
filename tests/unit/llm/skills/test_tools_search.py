"""search_skill_resources 工具（tools/search_resource.py）。"""
from __future__ import annotations

import pytest

from quickquip.llm.skills import (
    SkillActivationState,
    scan_skills,
    search_skill_resources,
)
from quickquip.llm.tools import LLMToolOutput

from tests.unit.llm.skills.conftest import load_single

_SCOPE = "s1"


def _activated_env(catalog_dir, name: str, **files):
    skill = load_single(catalog_dir, name)
    state = SkillActivationState()
    state.record(_SCOPE, name, skill.body_sha256)
    return {name: skill}, state


def _search(skills, state, query="关键词", name="demo", **kwargs):
    return search_skill_resources(
        skill_name=name,
        query=query,
        skills=skills,
        state=state,
        scope=_SCOPE,
        **kwargs,
    )


def test_search_gates(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "关键词"})
    skills = {skill.name: skill for skill in scan_skills(catalog_dir)}

    missing = _search(skills, SkillActivationState(), name="ghost")
    assert isinstance(missing, LLMToolOutput) and missing.is_error
    assert "未安装" in missing.content

    inactive = _search(skills, SkillActivationState())
    assert isinstance(inactive, LLMToolOutput) and inactive.is_error
    assert "尚未在当前会话激活" in inactive.content


def test_search_query_validation(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "内容"})
    skills, state = _activated_env(catalog_dir, "demo")

    empty = _search(skills, state, query="  ")
    assert isinstance(empty, LLMToolOutput) and empty.is_error
    assert "不能为空" in empty.content

    too_long = _search(skills, state, query="x" * 201)
    assert isinstance(too_long, LLMToolOutput) and too_long.is_error
    assert "200" in too_long.content

    bad_regex = _search(skills, state, query="[unclosed", is_regex=True)
    assert isinstance(bad_regex, LLMToolOutput) and bad_regex.is_error
    assert "正则表达式无效" in bad_regex.content


def test_search_literal_default_case_insensitive(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "Hello World\n另一行"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _search(skills, state, query="hello")
    assert isinstance(result, str)
    assert 'matches=1' in result
    assert "references/a.md:1:" in result
    assert "> 1 | Hello World" in result
    # +1 行上下文
    assert "  2 | 另一行" in result


def test_search_case_sensitive(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "Hello\nhello"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _search(skills, state, query="Hello", case_sensitive=True)
    assert "matches=1" in result
    assert "> 1 | Hello" in result


def test_search_regex_mode(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "错误码 E1001\n普通行\n错误码 E2042"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _search(skills, state, query=r"E\d{4}", is_regex=True)
    assert "matches=2" in result
    assert "> 1 | 错误码 E1001" in result
    assert "> 3 | 错误码 E2042" in result


def test_search_literal_escapes_regex_metachars(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "价格 100.00\n价格 100x00"})
    skills, state = _activated_env(catalog_dir, "demo")
    # 字面量模式："." 只匹配点号本身
    result = _search(skills, state, query="100.00")
    assert "matches=1" in result


def test_search_no_hits(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "完全无关"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _search(skills, state, query="不存在词")
    assert isinstance(result, str)
    assert "没有命中。" in result
    assert "matches=" not in result


def test_search_context_lines_clamped_at_file_edges(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "唯一行命中"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _search(skills, state, query="命中")
    # 单行文件：无上下文行也不报错
    assert "> 1 | 唯一行命中" in result


def test_search_max_results_truncates(make_skill):
    catalog_dir, writer = make_skill
    content = "\n".join(f"命中 {i}" for i in range(10))
    writer("demo", files={"references/a.md": content})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _search(skills, state, query="命中", max_results=3)
    assert "matches=3" in result
    assert "仅显示前 3 处" in result
    # 第 4 个命中（第 5 行）不得出现；第 4 行作为第 3 处命中的上下文可见
    assert "命中 4" not in result
    assert "> 4 |" not in result


def test_search_max_output_bytes_truncates(make_skill):
    catalog_dir, writer = make_skill
    content = "\n".join(f"很长的命中行 {i} " + "填" * 50 for i in range(20))
    writer("demo", files={"references/a.md": content})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _search(skills, state, query="命中", max_output_bytes=300)
    assert "仅显示前" in result
    assert len(result.encode("utf-8")) < 300 + 200  # 头部 + 尾部注记有界


def test_search_skips_binary_files_with_note(make_skill):
    catalog_dir, writer = make_skill
    writer(
        "demo",
        files={
            "references/a.md": "无关内容",
            "assets/blob.bin": b"\xff\xfe\x00\x01",
        },
    )
    skills, state = _activated_env(catalog_dir, "demo")
    result = _search(skills, state, query="词")
    assert "没有命中。" in result
    assert "跳过 1 个非 UTF-8 文件" in result


def test_search_only_scans_catalogued_resources(make_skill):
    """遍历范围 = 扫描时编入清单的资源；扫描后落盘的新文件不在检索面。"""
    catalog_dir, writer = make_skill
    root = writer("demo", files={"references/a.md": "无关"})
    skills, state = _activated_env(catalog_dir, "demo")
    (root / "references" / "late.md").write_text("关键词", encoding="utf-8")
    result = _search(skills, state, query="关键词")
    assert "没有命中。" in result


@pytest.mark.parametrize(
    "query",
    [
        r"(x+x+)+y",
        r"(.*)*b",
        r"(\w+\s*)+$",
        "(a|a)*",
        "(a|ab)*",
        "(a|)*",
        "((a+)b)*",
        r"(?P<name>x+)+y",
        "(?:x+x+)+",
        "(?i:a|a)+",
        # 相邻可空量化原子链（Deep-CR Blocking，生产实证形态）
        ".*.*.*.*z",
        ".*.*z",
        r"\s*\s*x",
        ".?.?.?.?QQQQ",
        "a?" * 5 + "b",
        # 量化符总数超上限
        "a+" * 21,
    ],
)
def test_search_rejects_pathological_regex(make_skill, query):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "xxxx"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _search(skills, state, query=query, is_regex=True)
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "灾难性回溯" in result.content
    assert "is_regex=false" in result.content


@pytest.mark.parametrize(
    "query",
    [
        r"E\d{4}",
        "(ab)+",
        "(错误|普通)行",
        "a+b{1,3}",
        "(a+(b|c)*)",
        "(ab|cd)+",
        "(a|bc)?",
        "(?i)(AB|CD)+",
        "(?<=x)y+",
        "a{1,2}|b{2}",
        # 防误杀：单个全能量词、非交叠/非全能相邻链、组保守不参与链
        "error.*timeout",
        "https?://",
        r"[\w.-]+@[\w.-]+\.\w+",
        ".*z",
        r"\d*\d*z",
        "(ab)?(cd)?",
    ],
)
def test_search_allows_benign_regex(make_skill, query):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "错误码 E1001\n普通行\nabab"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _search(skills, state, query=query, is_regex=True)
    assert not (isinstance(result, LLMToolOutput) and result.is_error), result


def test_search_pathological_pattern_literal_mode_unaffected(make_skill):
    """字面量模式不做正则静态检查，病态形态作为纯文本照常检索。"""
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "日志 (x+x+)+y 出现"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _search(skills, state, query="(x+x+)+y")
    assert isinstance(result, str)
    assert "matches=1" in result


def test_search_regex_lint_is_conservative_on_nested_quantifier(make_skill):
    """``(ab?)+`` 实际可安全匹配，但按"量化组内含量词即拒"的保守规则被拒。"""
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "abab"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _search(skills, state, query="(ab?)+", is_regex=True)
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "灾难性回溯" in result.content


def test_search_regex_match_timeout_interrupts_backtracking(make_skill, monkeypatch):
    """引擎超时层独立验证：禁用静态检查后，regex 引擎超时真正中断回溯。

    ``(a|aa)+c`` 是 regex 引擎也会灾难性回溯的形态（实测 >8s）；静态
    层本会先拒它（分支交叠），这里 monkeypatch 关掉第一层以单独验证
    第二层的调用级超时。
    """
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.txt": "a" * 60 + "\nplain\n"})
    skills, state = _activated_env(catalog_dir, "demo")
    monkeypatch.setattr(
        "quickquip.llm.skills.tools.search_resource._find_pathological_regex",
        lambda query: None,
    )
    monkeypatch.setattr(
        "quickquip.llm.skills.tools.search_resource._REGEX_MATCH_TIMEOUT_S", 0.05
    )
    result = _search(skills, state, query=r"(a|aa)+c", is_regex=True)
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "正则匹配超时" in result.content
    assert "is_regex=false" in result.content


def test_search_wall_clock_budget_returns_partial(make_skill, monkeypatch):
    """总预算耗尽时停止扫描并明确标注（防御纵深的第三层）。"""
    catalog_dir, writer = make_skill
    writer(
        "demo",
        files={"references/a.md": "命中甲\n", "references/b.md": "命中乙\n"},
    )
    skills, state = _activated_env(catalog_dir, "demo")
    monkeypatch.setattr(
        "quickquip.llm.skills.tools.search_resource._SEARCH_TIME_BUDGET_S", -1.0
    )
    result = _search(skills, state, query="命中")
    assert isinstance(result, str)
    assert "检索超时" in result


@pytest.mark.parametrize(
    ("fragment", "expected"),
    [
        ("a*", True),
        ("a?", True),
        ("a+", False),
        ("a{0,}", True),
        ("a{,5}", True),
        ("a{0,3}", True),
        ("a{0}", True),
        ("a{3,5}", False),
        ("a{2}", False),
    ],
)
def test_nullable_quantifier_boundaries(fragment, expected):
    from quickquip.llm.skills.tools.search_resource import _nullable_quantifier

    query = "x" + fragment + "y"
    assert _nullable_quantifier(query, 2) is expected
