"""catalog 扫描、路径加固与预算裁剪（catalog.py）。"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from quickquip.llm.skills import (
    MAX_RESOURCES_PER_SKILL,
    assert_safe_relative_path,
    build_catalog,
    classify_resource,
    derive_catalog_budget_bytes,
    resolve_skill_file,
    scan_skills,
    utf8_safe_boundary,
)


# ── 预算推导 ─────────────────────────────────────────────────────


def test_budget_window_unknown_uses_configured_cap():
    assert derive_catalog_budget_bytes(None, 8192) == 8192
    assert derive_catalog_budget_bytes(0, 4096) == 4096


def test_budget_min_of_window_two_percent_and_cap():
    # 窗口 100k token → 2% = 2000 token ×2 字节 = 4000 < 8192 上限
    assert derive_catalog_budget_bytes(100_000, 8192) == 4000
    # 窗口 1M token → 2% ×2 = 40000 > 8192 → 钳到上限
    assert derive_catalog_budget_bytes(1_000_000, 8192) == 8192


def test_budget_nonpositive_cap_falls_back():
    assert derive_catalog_budget_bytes(None, 0) == 8192
    assert derive_catalog_budget_bytes(None, -5) == 8192


# ── 路径加固 ─────────────────────────────────────────────────────


def test_safe_path_accepts_plain_relative():
    assert_safe_relative_path("references/index.md")
    assert_safe_relative_path("a")


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../escape",
        "a/../b",
        "/abs/path",
        "C:/win/abs",
        "back\\slash",
        "a//b",
        "./dot",
        "nul\0byte",
    ],
)
def test_safe_path_rejects_unsafe_shapes(path):
    with pytest.raises(ValueError):
        assert_safe_relative_path(path)


def test_classify_resource_top_level_dirs():
    assert classify_resource("references/a.md") == "reference"
    assert classify_resource("assets/logo.png") == "asset"
    assert classify_resource("scripts/run.py") == "script"
    assert classify_resource("notes.txt") == "other"


def test_utf8_safe_boundary_never_splits_multibyte():
    raw = "中文测试".encode("utf-8")  # 每字 3 字节
    boundary = utf8_safe_boundary(raw, 4)
    assert boundary == 3
    assert raw[:boundary].decode("utf-8") == "中"
    # 上限超过全长时收敛到全长
    assert utf8_safe_boundary(raw, 100) == len(raw)


# ── 目录扫描 ─────────────────────────────────────────────────────


def test_scan_missing_dir_returns_empty_without_log(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert scan_skills(tmp_path / "nonexistent") == []
    assert caplog.records == []


def test_scan_tolerates_catalog_iterdir_oserror(make_skill, monkeypatch, caplog):
    """is_dir 通过而 iterdir 失败（扫描瞬间目录被移走）：warn 并返回 []。"""
    catalog_dir, writer = make_skill
    writer("demo")
    real_iterdir = Path.iterdir

    def flaky_iterdir(self):
        if self == catalog_dir:
            raise OSError("No such file or directory")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", flaky_iterdir)
    with caplog.at_level(logging.WARNING):
        assert scan_skills(catalog_dir) == []
    assert any("目录读取失败" in record.message for record in caplog.records)


def test_scan_tolerates_resource_stat_oserror(make_skill, monkeypatch):
    """walk 列名与 stat 之间资源文件消失：记 read-error 诊断跳过，skill 照常加载。"""
    catalog_dir, writer = make_skill
    writer("demo", files={"references/a.md": "内容"})
    real_stat = Path.stat
    real_is_file = Path.is_file

    def flaky_stat(self, *args, **kwargs):
        # lstat 委托 stat(follow_symlinks=False)：只对真实 stat 调用模拟消失。
        if self.name == "a.md" and kwargs.get("follow_symlinks", True):
            raise OSError("No such file or directory")
        return real_stat(self, *args, **kwargs)

    def fake_is_file(self):
        if self.name == "a.md":
            return True
        return real_is_file(self)

    monkeypatch.setattr(Path, "stat", flaky_stat)
    monkeypatch.setattr(Path, "is_file", fake_is_file)
    (skill,) = scan_skills(catalog_dir)
    assert skill.name == "demo"
    assert skill.resources == []
    assert any(d.kind == "read-error" for d in skill.diagnostics)


def test_scan_loads_valid_skill_with_resources(make_skill):
    catalog_dir, writer = make_skill
    writer(
        "demo",
        "演示。",
        body="正文。\n",
        files={
            "references/index.md": "参考内容",
            "scripts/run.py": "print('hi')\n",
            "assets/note.txt": "资产",
        },
    )
    skills = scan_skills(catalog_dir)
    assert [skill.name for skill in skills] == ["demo"]
    skill = skills[0]
    assert skill.body == "正文。\n"
    by_path = {resource.path: resource for resource in skill.resources}
    assert set(by_path) == {"references/index.md", "scripts/run.py", "assets/note.txt"}
    assert by_path["references/index.md"].kind == "reference"
    assert by_path["scripts/run.py"].kind == "script"
    # 仅 scripts/ 计算 sha256（run_skill_script 复验消费）
    assert by_path["scripts/run.py"].sha256
    assert by_path["references/index.md"].sha256 == ""


def test_scan_sorted_by_name(make_skill):
    catalog_dir, writer = make_skill
    writer("zeta")
    writer("alpha")
    writer("mid")
    assert [skill.name for skill in scan_skills(catalog_dir)] == ["alpha", "mid", "zeta"]


def test_scan_skips_bad_skill_keeps_good_neighbor(make_skill, caplog):
    catalog_dir, writer = make_skill
    writer("good", "好邻居。")
    bad = catalog_dir / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("没有 frontmatter", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        skills = scan_skills(catalog_dir)
    assert [skill.name for skill in skills] == ["good"]
    assert any("bad" in record.getMessage() for record in caplog.records)


def test_scan_skips_symlink_root(make_skill, tmp_path):
    catalog_dir, writer = make_skill
    real = writer("real-skill")
    (catalog_dir / "linked").symlink_to(real, target_is_directory=True)
    skills = scan_skills(catalog_dir)
    assert [skill.name for skill in skills] == ["real-skill"]


def test_scan_skips_dir_without_skill_md(make_skill):
    catalog_dir, _ = make_skill
    (catalog_dir / "empty-dir").mkdir()
    assert scan_skills(catalog_dir) == []


def test_scan_strips_utf8_bom(make_skill):
    catalog_dir, _ = make_skill
    root = catalog_dir / "bom-skill"
    root.mkdir()
    content = "---\nname: bom-skill\ndescription: 带 BOM。\n---\n正文\n"
    (root / "SKILL.md").write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
    skills = scan_skills(catalog_dir)
    assert [skill.name for skill in skills] == ["bom-skill"]


def test_scan_rejects_invalid_utf8_skill_md(make_skill, caplog):
    catalog_dir, _ = make_skill
    root = catalog_dir / "broken"
    root.mkdir()
    (root / "SKILL.md").write_bytes(b"\xff\xfe\x00\x01")
    with caplog.at_level(logging.WARNING):
        assert scan_skills(catalog_dir) == []
    assert any("broken" in record.getMessage() for record in caplog.records)


def test_scan_excludes_symlink_resource_with_diagnostic(make_skill, tmp_path):
    catalog_dir, writer = make_skill
    outside = tmp_path / "secret.txt"
    outside.write_text("机密", encoding="utf-8")
    root = writer("demo", files={"references/ok.md": "正常"})
    (root / "references" / "leak.md").symlink_to(outside)
    (skill,) = scan_skills(catalog_dir)
    assert [resource.path for resource in skill.resources] == ["references/ok.md"]
    assert any(d.kind == "resource-symlink" for d in skill.diagnostics)


def test_scan_resource_count_capped(make_skill):
    catalog_dir, writer = make_skill
    files = {f"references/f{i:03d}.md": "x" for i in range(MAX_RESOURCES_PER_SKILL + 5)}
    writer("demo", files=files)
    (skill,) = scan_skills(catalog_dir)
    assert len(skill.resources) == MAX_RESOURCES_PER_SKILL
    assert any(d.kind == "resource-count-oversize" for d in skill.diagnostics)


def test_resolve_skill_file_rejects_symlink_escape(make_skill, tmp_path):
    catalog_dir, writer = make_skill
    outside = tmp_path / "secret.txt"
    outside.write_text("机密", encoding="utf-8")
    root = writer("demo")
    (root / "leak.txt").symlink_to(outside)
    (skill,) = scan_skills(catalog_dir)
    with pytest.raises(ValueError, match="常规文件"):
        resolve_skill_file(skill, "leak.txt")
    with pytest.raises(ValueError, match="不存在"):
        resolve_skill_file(skill, "missing.txt")


# ── build_catalog 预算裁剪 ───────────────────────────────────────


def test_catalog_entries_sorted_and_hash_stable(make_skill):
    catalog_dir, writer = make_skill
    writer("zeta", "三。")
    writer("alpha", "一。")
    skills = scan_skills(catalog_dir)
    first = build_catalog(skills, budget_bytes=8192)
    second = build_catalog(scan_skills(catalog_dir), budget_bytes=8192)
    assert first.names == ["alpha", "zeta"]
    assert first.hash == second.hash
    assert first.omitted == []
    assert set(first.by_name) == {"alpha", "zeta"}


def test_catalog_hash_changes_with_body_not_description(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", "描述。", body="正文 v1")
    before = build_catalog(scan_skills(catalog_dir), budget_bytes=8192).hash
    writer("demo", "描述。", body="正文 v2")
    after = build_catalog(scan_skills(catalog_dir), budget_bytes=8192).hash
    assert before != after


def test_catalog_shortens_descriptions_before_dropping(make_skill):
    catalog_dir, writer = make_skill
    long_desc = "长" * 200
    writer("aaa", long_desc)
    writer("bbb", long_desc)
    skills = scan_skills(catalog_dir)
    full = build_catalog(skills, budget_bytes=8192)
    full_bytes = len(
        "".join(f"{e.name}\n{e.description}\n" for e in full.entries).encode("utf-8")
    )
    # 预算略小于全量但大于全截短形态 → 先截短（160 字符）不淘汰
    budget = full_bytes - 1
    catalog = build_catalog(skills, budget_bytes=budget)
    assert catalog.names == ["aaa", "bbb"]
    assert catalog.omitted == []
    assert all(len(entry.description) <= 160 for entry in catalog.entries)
    assert any(entry.description.endswith("…") for entry in catalog.entries)


def test_catalog_drops_lexicographic_tail_when_over_budget(make_skill, caplog):
    catalog_dir, writer = make_skill
    # ASCII 描述使字节账可预期：最短形态 80 字符 = 80 字节/条。
    writer("aaa", "a" * 200)
    writer("bbb", "b" * 200)
    writer("ccc", "c" * 200)
    skills = scan_skills(catalog_dir)
    # 单条最短形态 = name(3)+\n+80+\n = 85 字节；预算 200 只容两条（170 ≤ 200 < 255）
    with caplog.at_level(logging.WARNING):
        catalog = build_catalog(skills, budget_bytes=200)
    assert catalog.names == ["aaa", "bbb"]
    assert catalog.omitted == ["ccc"]
    assert set(catalog.by_name) == {"aaa", "bbb"}
    assert any("淘汰" in record.getMessage() for record in caplog.records)


def test_catalog_never_drops_last_entry(make_skill):
    catalog_dir, writer = make_skill
    writer("solo", "独" * 500, body="正文")
    (skill,) = scan_skills(catalog_dir)
    catalog = build_catalog([skill], budget_bytes=1)
    assert catalog.names == ["solo"]
    assert catalog.omitted == []
    # by_name 指向原始未截短 skill，激活依旧可行
    assert catalog.by_name["solo"] is skill


def test_catalog_deterministic_render_order_independent_of_input_order(make_skill):
    catalog_dir, writer = make_skill
    writer("b-skill", "二。")
    writer("a-skill", "一。")
    skills = scan_skills(catalog_dir)
    forward = build_catalog(skills, budget_bytes=8192)
    reverse = build_catalog(list(reversed(skills)), budget_bytes=8192)
    assert forward.names == reverse.names == ["a-skill", "b-skill"]
    assert forward.hash == reverse.hash
