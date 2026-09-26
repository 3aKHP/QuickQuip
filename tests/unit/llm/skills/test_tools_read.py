"""read_skill_resource 工具（tools/read_resource.py）。"""
from __future__ import annotations

from quickquip.llm.skills import (
    SkillActivationState,
    read_skill_resource,
    scan_skills,
)
from quickquip.llm.tools import LLMToolOutput

from tests.unit.llm.skills.conftest import load_single

_SCOPE = "s1"


def _activated_env(catalog_dir, name: str):
    skill = load_single(catalog_dir, name)
    state = SkillActivationState()
    state.record(_SCOPE, name, skill.body_sha256)
    return {name: skill}, state


def _read(skills, state, name="demo", path="references/index.md", **kwargs):
    kwargs.setdefault("max_bytes", 65536)
    return read_skill_resource(
        skill_name=name, path=path, skills=skills, state=state, scope=_SCOPE, **kwargs
    )


def test_read_requires_installed_skill(make_skill):
    catalog_dir, writer = make_skill
    writer("demo")
    skills, state = _activated_env(catalog_dir, "demo")
    result = _read(skills, state, name="ghost", path="references/index.md")
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "未安装" in result.content


def test_read_requires_activated_skill(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/index.md": "内容"})
    skills = {skill.name: skill for skill in scan_skills(catalog_dir)}
    result = _read(skills, SkillActivationState())
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "尚未在当前会话激活" in result.content


def test_read_rejects_unsafe_paths(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/index.md": "内容"})
    skills, state = _activated_env(catalog_dir, "demo")
    for bad in ("../SKILL.md", "/etc/passwd", "references\\index.md", "references//x", ""):
        result = _read(skills, state, path=bad)
        assert isinstance(result, LLMToolOutput) and result.is_error, bad


def test_read_rejects_symlink_escape(make_skill, tmp_path):
    catalog_dir, writer = make_skill
    outside = tmp_path / "secret.txt"
    outside.write_text("机密内容", encoding="utf-8")
    root = writer("demo")
    (root / "leak.txt").symlink_to(outside)
    skills, state = _activated_env(catalog_dir, "demo")
    result = _read(skills, state, path="leak.txt")
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "机密内容" not in result.content


def test_read_missing_file(make_skill):
    catalog_dir, writer = make_skill
    writer("demo")
    skills, state = _activated_env(catalog_dir, "demo")
    result = _read(skills, state, path="references/none.md")
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "不存在" in result.content


def test_read_returns_content_with_header(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/index.md": "第一行\n第二行"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _read(skills, state)
    assert isinstance(result, str)
    assert result.startswith('[skill_resource name="demo" path="references/index.md"]\n')
    assert "第一行\n第二行" in result


def test_read_truncates_over_max_bytes_utf8_safe(make_skill):
    catalog_dir, writer = make_skill
    # 100 个"中"（300 字节）+ 尾巴
    writer("demo", files={"references/big.md": "中" * 100 + "END"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _read(skills, state, path="references/big.md", max_bytes=10)
    assert isinstance(result, str)
    assert "已截断" in result
    assert "END" not in result
    # 10 字节预算落在"中"（3 字节）序列内 → 安全边界截到 9 字节 = 3 个"中"
    body = result.split("\n")[1]
    assert body == "中中中"


def test_read_rejects_non_utf8(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"assets/bin.dat": b"\xff\xfe\x00\x01"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _read(skills, state, path="assets/bin.dat")
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "不是有效 UTF-8" in result.content


def test_read_line_range_slice(make_skill):
    catalog_dir, writer = make_skill
    content = "\n".join(f"第{i}行" for i in range(1, 11))
    writer("demo", files={"references/lines.md": content})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _read(skills, state, path="references/lines.md", start_line=3, end_line=5)
    assert isinstance(result, str)
    assert "第3行\n第4行\n第5行" in result
    assert "第2行" not in result
    assert "[第 3-5 行，共 10 行]" in result


def test_read_invalid_line_ranges(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/lines.md": "a\nb\nc"})
    skills, state = _activated_env(catalog_dir, "demo")
    for kwargs in (
        {"start_line": 0},
        {"end_line": -1},
        {"start_line": 5, "end_line": 2},
    ):
        result = _read(skills, state, path="references/lines.md", **kwargs)
        assert isinstance(result, LLMToolOutput) and result.is_error, kwargs


def test_read_end_line_beyond_eof_clamps(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/lines.md": "a\nb\nc"})
    skills, state = _activated_env(catalog_dir, "demo")
    result = _read(skills, state, path="references/lines.md", start_line=2, end_line=99)
    assert isinstance(result, str)
    assert "b\nc" in result
    assert "[第 2-3 行，共 3 行]" in result
