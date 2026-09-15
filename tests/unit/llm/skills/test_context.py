"""catalog 块 / 激活标记块 / /skill list 渲染（context.py）。"""
from __future__ import annotations

from quickquip.llm.skills import (
    ACTIVATION_STATUS_ACTIVATED,
    ACTIVATION_STATUS_ALREADY_ACTIVE,
    build_catalog,
    format_activation_block,
    render_catalog_block,
    render_skill_list,
    scan_skills,
)


def _catalog(catalog_dir, budget: int = 8192):
    return build_catalog(scan_skills(catalog_dir), budget_bytes=budget)


# ── render_catalog_block ─────────────────────────────────────────


def test_catalog_block_empty_catalog_renders_empty():
    catalog = build_catalog([], budget_bytes=8192)
    assert render_catalog_block(catalog) == ""


def test_catalog_block_format(make_skill):
    catalog_dir, writer = make_skill
    writer("alpha", "一。")
    writer("beta", "二。")
    catalog = _catalog(catalog_dir)
    block = render_catalog_block(catalog)
    lines = block.split("\n")
    assert lines[0] == f'<skill_catalog hash="{catalog.hash}">'
    assert lines[-1] == "</skill_catalog>"
    assert "- alpha: 一。" in lines
    assert "- beta: 二。" in lines
    # 路由信息从属规则行常驻
    assert any("activate_skill" in line for line in lines)


def test_catalog_block_omitted_line(make_skill):
    catalog_dir, writer = make_skill
    # 截短形态 = 79 字符 + "…"（3 字节）→ 单条 87 字节；预算 180 容两条不容三条。
    writer("aaa", "a" * 200)
    writer("bbb", "b" * 200)
    writer("ccc", "c" * 200)
    catalog = _catalog(catalog_dir, budget=180)
    assert catalog.omitted == ["ccc"]
    block = render_catalog_block(catalog)
    assert "另有 1 个 Skill 因目录预算超限未列出" in block
    assert "- ccc:" not in block


def test_catalog_block_byte_stable_for_same_dir(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", "稳定。")
    first = render_catalog_block(_catalog(catalog_dir))
    second = render_catalog_block(_catalog(catalog_dir))
    assert first == second
    # 目录内容变化 → 块字节变化（等效新纪元）
    writer("another", "新增。")
    assert render_catalog_block(_catalog(catalog_dir)) != first


# ── format_activation_block ──────────────────────────────────────


def test_activation_block_activated_contains_marker_body_resources(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", "演示。", body="指令正文第一行。\n", files={"references/a.md": "参考"})
    (skill,) = scan_skills(catalog_dir)
    block = format_activation_block(skill, status=ACTIVATION_STATUS_ACTIVATED)
    assert block.startswith(
        f'[skill_activation name="demo" hash="{skill.body_sha256}" status="activated"]'
    )
    assert "指令正文第一行。" in block
    assert "[/skill_activation]" in block
    assert "references/a.md" in block
    assert "read_skill_resource" in block
    assert "从属于机器人规则" in block


def test_activation_block_activated_lists_no_resources(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", "演示。", body="只有正文。")
    (skill,) = scan_skills(catalog_dir)
    block = format_activation_block(skill, status=ACTIVATION_STATUS_ACTIVATED)
    assert "附带资源：无。" in block


def test_activation_block_already_active_is_short_without_body(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", "演示。", body="不应重复注入的正文。")
    (skill,) = scan_skills(catalog_dir)
    block = format_activation_block(skill, status=ACTIVATION_STATUS_ALREADY_ACTIVE)
    assert 'status="already-active"' in block
    assert "已激活且内容相同" in block
    assert "不应重复注入的正文" not in block
    assert "附带资源" not in block


def test_activation_block_includes_diagnostics(make_skill, tmp_path):
    catalog_dir, writer = make_skill
    root = writer("demo", "演示。", body="正文", files={"references/ok.md": "x"})
    outside = tmp_path / "outside.txt"
    outside.write_text("y", encoding="utf-8")
    (root / "references" / "leak.md").symlink_to(outside)
    (skill,) = scan_skills(catalog_dir)
    assert skill.diagnostics  # resource-symlink 诊断
    block = format_activation_block(skill, status=ACTIVATION_STATUS_ACTIVATED)
    assert "诊断信息：" in block
    assert "resource-symlink" in block


# ── render_skill_list ────────────────────────────────────────────


def test_skill_list_empty():
    assert render_skill_list([], []) == "当前未安装任何 Skill。"


def test_skill_list_with_activation(make_skill):
    catalog_dir, writer = make_skill
    writer("alpha", "一。")
    writer("beta", "二。")
    skills = scan_skills(catalog_dir)
    text = render_skill_list(skills, ["beta"])
    assert "已安装 Skill（2）：" in text
    assert "- alpha：一。" in text
    assert "- beta：二。" in text
    assert "当前会话已激活：beta" in text


def test_skill_list_without_activation(make_skill):
    catalog_dir, writer = make_skill
    writer("alpha", "一。")
    text = render_skill_list(scan_skills(catalog_dir), [])
    assert "当前会话已激活：（无）" in text
