"""SKILL.md frontmatter 解析与校验（parser.parse_skill_markdown）。"""
from __future__ import annotations

import hashlib

from quickquip.llm.skills import (
    MAX_DESCRIPTION_CHARS,
    MAX_SKILL_FILE_BYTES,
    parse_skill_markdown,
)

from tests.unit.llm.skills.conftest import skill_markdown


def _kinds(result) -> list[str]:
    return [diagnostic.kind for diagnostic in result.diagnostics]


def test_parse_minimal_valid():
    body = "第一段指令。\n\n第二段。\n"
    result = parse_skill_markdown(skill_markdown("demo", "演示 skill。", body=body))
    assert result.ok
    assert result.metadata is not None
    assert result.metadata.name == "demo"
    assert result.metadata.description == "演示 skill。"
    assert result.body == body
    assert result.body_sha256 == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert result.diagnostics == []


def test_parse_missing_opening_fence():
    result = parse_skill_markdown("name: demo\ndescription: x\n")
    assert not result.ok
    assert _kinds(result) == ["missing-frontmatter"]


def test_parse_missing_closing_fence():
    result = parse_skill_markdown("---\nname: demo\ndescription: x\n")
    assert not result.ok
    assert _kinds(result) == ["missing-closing-fence"]


def test_parse_bad_yaml():
    result = parse_skill_markdown("---\nname: [unclosed\n---\nbody\n")
    assert not result.ok
    assert _kinds(result) == ["parse-error"]


def test_parse_frontmatter_not_mapping():
    result = parse_skill_markdown("---\n- just\n- a\n- list\n---\nbody\n")
    assert not result.ok
    assert _kinds(result) == ["parse-error"]


def test_parse_name_missing_or_blank():
    for frontmatter in ("description: x\n", 'name: ""\ndescription: x\n'):
        result = parse_skill_markdown(f"---\n{frontmatter}---\nbody\n")
        assert not result.ok
        assert "name-missing" in _kinds(result)


def test_parse_name_pattern_violations():
    for bad_name in ("Bad", "-lead", "_under", "has space", "中文字符"):
        result = parse_skill_markdown(skill_markdown(bad_name, "x"))
        assert not result.ok, bad_name
        assert "name-invalid" in _kinds(result)


def test_parse_name_allows_digits_and_inner_hyphens():
    for good_name in ("abc", "a1", "1abc", "my-skill-2", "trailing-"):
        result = parse_skill_markdown(skill_markdown(good_name, "x"))
        assert result.ok, good_name


def test_parse_name_too_long():
    result = parse_skill_markdown(skill_markdown("a" * 65, "x"))
    assert not result.ok
    assert "name-invalid" in _kinds(result)


def test_parse_name_directory_mismatch():
    result = parse_skill_markdown(
        skill_markdown("demo", "x"), expected_name="other"
    )
    assert not result.ok
    assert "name-directory-mismatch" in _kinds(result)


def test_parse_name_matches_directory():
    result = parse_skill_markdown(skill_markdown("demo", "x"), expected_name="demo")
    assert result.ok


def test_parse_description_missing_or_blank():
    for frontmatter in ("name: demo\n", 'name: demo\ndescription: ""\n'):
        result = parse_skill_markdown(f"---\n{frontmatter}---\nbody\n")
        assert not result.ok
        assert "description-missing" in _kinds(result)


def test_parse_description_oversized():
    result = parse_skill_markdown(
        skill_markdown("demo", "x" * (MAX_DESCRIPTION_CHARS + 1))
    )
    assert not result.ok
    assert "description-oversized" in _kinds(result)


def test_parse_file_oversized():
    oversized = skill_markdown("demo", "x", body="y" * MAX_SKILL_FILE_BYTES)
    result = parse_skill_markdown(oversized)
    assert not result.ok
    assert _kinds(result) == ["oversized-skill"]


def test_parse_unknown_fields_kept_as_diagnostics_only():
    result = parse_skill_markdown(
        skill_markdown("demo", "x", frontmatter_extra="author: 某人\nweird-key: 1")
    )
    assert result.ok
    assert "unsupported-field" in _kinds(result)
    assert result.metadata is not None
    assert result.metadata.unknown_fields == ("author", "weird-key")


def test_parse_allowed_tools_ignored_with_diagnostic():
    result = parse_skill_markdown(
        skill_markdown("demo", "x", frontmatter_extra='allowed-tools: ["Bash"]')
    )
    assert result.ok
    assert "allowed-tools-ignored" in _kinds(result)


def test_parse_license_compatibility_and_metadata_map():
    extra = (
        "license: MIT\n"
        "compatibility: python>=3.12\n"
        "metadata:\n"
        "  version: 3\n"
        "  tier: beta\n"
    )
    result = parse_skill_markdown(skill_markdown("demo", "x", frontmatter_extra=extra))
    assert result.ok
    assert result.metadata is not None
    assert result.metadata.license == "MIT"
    assert result.metadata.compatibility == "python>=3.12"
    # 标量值统一转字符串
    assert result.metadata.metadata == {"version": "3", "tier": "beta"}


def test_parse_metadata_nested_value_rejected():
    extra = "metadata:\n  nested:\n    deep: true\n"
    result = parse_skill_markdown(skill_markdown("demo", "x", frontmatter_extra=extra))
    assert not result.ok
    assert "parse-error" in _kinds(result)


def test_parse_crlf_fences_tolerated():
    result = parse_skill_markdown("---\r\nname: demo\r\ndescription: x\r\n---\r\nbody\r\n")
    assert result.ok
