"""routes/skills.py 端点级用例（monkeypatch 模块常量 + 直接调路由函数）。

摄取护栏、stash、GitHub URL/下载的管线级用例在 test_skill_import.py。
"""

import base64
import io
import math
import re
import stat
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException

from pydantic import ValidationError  # noqa: E402

from quickquip.app.web import skill_import  # noqa: E402
from quickquip.app.web.routes import skills  # noqa: E402
from quickquip.app.web.routes.skills import _effective_catalog_dir  # noqa: E402
from quickquip.common.paths import SKILLS_DIR  # noqa: E402
from quickquip.llm.skills import preset_sync  # noqa: E402


def _mock_request():
    req = MagicMock()
    req.client.host = "127.0.0.1"
    return req


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    monkeypatch.setattr(skills.audit_logger, "log", lambda *args, **kwargs: None)


@pytest.fixture
def audit_trail(monkeypatch):
    """捕获审计调用的（覆写 autouse 的 no-op）。"""
    trail: list[dict] = []
    monkeypatch.setattr(
        skills.audit_logger,
        "log",
        lambda request, **kwargs: trail.append(kwargs),
    )
    return trail


@pytest.fixture
def catalog_dir(monkeypatch, tmp_path) -> Path:
    directory = tmp_path / "skills"
    directory.mkdir()
    monkeypatch.setattr(skills, "_effective_catalog_dir", lambda: directory)
    return directory


@pytest.fixture
def example_dir(monkeypatch, tmp_path) -> Path:
    directory = tmp_path / "skills.example"
    directory.mkdir()
    monkeypatch.setattr(skills, "_EXAMPLE_DIR", directory)
    return directory


@pytest.fixture
def stash_dir(monkeypatch, tmp_path) -> Path:
    directory = tmp_path / "stash"
    monkeypatch.setattr(skills, "_STASH_DIR", directory)
    return directory


def _skill_md(name: str, description: str = "A test skill") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\nBody text.\n"


def _write_skill(base: Path, name: str, *, extra: dict[str, bytes] | None = None) -> Path:
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_skill_md(name), encoding="utf-8")
    for relative, data in (extra or {}).items():
        target = skill_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return skill_dir


def _make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return buffer.getvalue()


def _zip_b64(files: dict[str, bytes]) -> str:
    return base64.b64encode(_make_zip(files)).decode("ascii")


def _inspect_zip(files: dict[str, bytes]) -> dict:
    return skills.inspect_import(
        skills.ImportInspectBody(kind="zip", archive_b64=_zip_b64(files))
    )


# ── 列表 ─────────────────────────────────────────────────────────


def test_list_skills_mixed_good_and_bad(catalog_dir):
    _write_skill(
        catalog_dir,
        "good",
        extra={"scripts/run.sh": b"echo hi\n", "references/doc.md": b"# doc\n"},
    )
    (catalog_dir / "no-skill-md").mkdir()
    # 解析失败：frontmatter name 与目录名不一致
    _write_skill(catalog_dir, "bad-parse")
    (catalog_dir / "bad-parse" / "SKILL.md").write_text(
        _skill_md("other-name"), encoding="utf-8"
    )
    (catalog_dir / preset_sync.BACKUP_CONTAINER_NAME).mkdir(exist_ok=True)

    result = skills.list_skills()

    items = {item["name"]: item for item in result["skills"]}
    assert preset_sync.BACKUP_CONTAINER_NAME not in items
    good = items["good"]
    assert good["ok"] is True
    assert good["description"] == "A test skill"
    assert good["has_scripts"] is True
    assert good["resource_count"] == 2
    assert good["total_bytes"] > 0
    assert good["mtime"] > 0
    assert good["preset_state"] is None
    assert items["no-skill-md"]["ok"] is False
    assert [d["kind"] for d in items["no-skill-md"]["diagnostics"]] == ["missing-skill-file"]
    assert items["bad-parse"]["ok"] is False
    assert [d["kind"] for d in items["bad-parse"]["diagnostics"]] == [
        "name-directory-mismatch"
    ]


def test_list_skills_excludes_staging_and_lock_artifacts(catalog_dir):
    """.install-* 暂存目录与 catalog 根的锁文件不作为 skill 出现。"""
    _write_skill(catalog_dir, "good")
    (catalog_dir / ".install-orphan").mkdir()
    (catalog_dir / "good.lock").write_text("", encoding="utf-8")

    result = skills.list_skills()

    assert [item["name"] for item in result["skills"]] == ["good"]


def test_list_skills_marks_preset_state(catalog_dir, example_dir):
    _write_skill(example_dir, "preset-a")
    _write_skill(catalog_dir, "preset-a")
    _write_skill(example_dir, "preset-b")
    _write_skill(catalog_dir, "preset-b", extra={"local.txt": b"custom\n"})

    result = skills.list_skills()

    items = {item["name"]: item for item in result["skills"]}
    assert items["preset-a"]["preset_state"] == "current"
    assert items["preset-b"]["preset_state"] == "diverged"


# ── 详情与文件读 ──────────────────────────────────────────────────


def test_get_skill_detail(catalog_dir):
    _write_skill(catalog_dir, "good", extra={"scripts/run.sh": b"echo hi\n"})

    result = skills.get_skill("good")

    assert result["name"] == "good"
    assert result["metadata"]["name"] == "good"
    assert result["metadata"]["description"] == "A test skill"
    assert "Body text." in result["body"]
    script = next(r for r in result["resources"] if r["kind"] == "script")
    assert script["path"] == "scripts/run.sh"
    assert script["sha256"]
    assert result["diagnostics"] == []


def test_get_skill_missing_404(catalog_dir):
    with pytest.raises(HTTPException) as exc:
        skills.get_skill("nope")
    assert exc.value.status_code == 404


def test_get_skill_broken_404_with_diagnostics(catalog_dir):
    (catalog_dir / "broken").mkdir()

    with pytest.raises(HTTPException) as exc:
        skills.get_skill("broken")

    assert exc.value.status_code == 404
    assert exc.value.detail["diagnostics"][0]["kind"] == "missing-skill-file"


def test_get_skill_invalid_name_422(catalog_dir):
    with pytest.raises(HTTPException) as exc:
        skills.get_skill("Bad Name")
    assert exc.value.status_code == 422


def test_symlink_skill_dir_is_404(catalog_dir, tmp_path):
    """符号链接形态的 skill 目录一律 404（不随链接操作外部目录）。"""
    outside = tmp_path / "outside-skill"
    outside.mkdir()
    (outside / "SKILL.md").write_text(_skill_md("linked"), encoding="utf-8")
    (catalog_dir / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(HTTPException) as exc:
        skills.get_skill("linked")
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        skills.delete_skill("linked", _mock_request())
    assert exc.value.status_code == 404
    assert (outside / "SKILL.md").exists()


def test_read_skill_file_ok(catalog_dir):
    _write_skill(catalog_dir, "good", extra={"references/doc.md": "你好\n".encode()})

    result = skills.read_skill_file("good", "references/doc.md")

    assert result["content"] == "你好\n"
    assert result["size_bytes"] == len("你好\n".encode())


def test_read_skill_file_traversal_422(catalog_dir):
    _write_skill(catalog_dir, "good")

    with pytest.raises(HTTPException) as exc:
        skills.read_skill_file("good", "../outside.md")

    assert exc.value.status_code == 422


def test_read_skill_file_non_utf8_415(catalog_dir):
    _write_skill(catalog_dir, "good", extra={"assets/raw.bin": b"\xff\xfe\x00"})

    with pytest.raises(HTTPException) as exc:
        skills.read_skill_file("good", "assets/raw.bin")

    assert exc.value.status_code == 415


def test_read_skill_file_oversize_413(catalog_dir):
    _write_skill(
        catalog_dir, "good", extra={"references/big.md": b"a" * (256 * 1024 + 1)}
    )

    with pytest.raises(HTTPException) as exc:
        skills.read_skill_file("good", "references/big.md")

    assert exc.value.status_code == 413


def test_read_skill_file_missing_404(catalog_dir):
    _write_skill(catalog_dir, "good")

    with pytest.raises(HTTPException) as exc:
        skills.read_skill_file("good", "references/none.md")

    assert exc.value.status_code == 404


# ── 文件写 / 删 ────────────────────────────────────────────────────


def test_write_skill_file_rejects_invalid_skill_md(catalog_dir):
    _write_skill(catalog_dir, "good")

    with pytest.raises(HTTPException) as exc:
        skills.write_skill_file(
            "good",
            skills.SkillFileWriteBody(path="SKILL.md", content=_skill_md("other")),
            _mock_request(),
        )

    assert exc.value.status_code == 400
    assert [d["kind"] for d in exc.value.detail["diagnostics"]] == [
        "name-directory-mismatch"
    ]


def test_write_skill_file_upsert_atomic_and_audit(catalog_dir, audit_trail):
    skill_dir = _write_skill(catalog_dir, "good")

    skills.write_skill_file(
        "good",
        skills.SkillFileWriteBody(path="references/new.md", content="first\n"),
        _mock_request(),
    )
    skills.write_skill_file(
        "good",
        skills.SkillFileWriteBody(path="references/new.md", content="second\n"),
        _mock_request(),
    )

    target = skill_dir / "references" / "new.md"
    assert target.read_text(encoding="utf-8") == "second\n"
    # 原子写：不残留 tmp 文件
    assert not (skill_dir / "references" / "new.md.tmp").exists()
    # B1：锁文件在 catalog 根，skill 内容树内无 .lock 残留
    assert list(skill_dir.rglob("*.lock")) == []
    assert (catalog_dir / "good.lock").exists()
    assert [entry["action"] for entry in audit_trail] == ["create", "update"]
    assert [entry["target_id"] for entry in audit_trail] == [
        "good:references/new.md",
        "good:references/new.md",
    ]


def test_write_skill_file_traversal_422(catalog_dir):
    _write_skill(catalog_dir, "good")

    with pytest.raises(HTTPException) as exc:
        skills.write_skill_file(
            "good",
            skills.SkillFileWriteBody(path="../evil.md", content="x"),
            _mock_request(),
        )

    assert exc.value.status_code == 422


def test_write_skill_file_missing_skill_404(catalog_dir):
    with pytest.raises(HTTPException) as exc:
        skills.write_skill_file(
            "ghost",
            skills.SkillFileWriteBody(path="references/x.md", content="x"),
            _mock_request(),
        )

    assert exc.value.status_code == 404


def test_write_skill_file_parent_is_file_409(catalog_dir):
    """路径中间段是既有文件：mkdir 失败映射为 409 而非裸 500。"""
    skill_dir = _write_skill(catalog_dir, "good")
    (skill_dir / "notes").write_text("a file, not a dir\n", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        skills.write_skill_file(
            "good",
            skills.SkillFileWriteBody(path="notes/x.md", content="x"),
            _mock_request(),
        )

    assert exc.value.status_code == 409


def test_write_skill_file_through_symlinked_dir_422(catalog_dir, tmp_path):
    """skill 内 references 是指向外部目录的符号链接：写入 422，外部无变化。"""
    skill_dir = _write_skill(catalog_dir, "good")
    outside = tmp_path / "outside"
    outside.mkdir()
    (skill_dir / "references").symlink_to(outside, target_is_directory=True)

    with pytest.raises(HTTPException) as exc:
        skills.write_skill_file(
            "good",
            skills.SkillFileWriteBody(path="references/evil.md", content="x"),
            _mock_request(),
        )

    assert exc.value.status_code == 422
    assert list(outside.iterdir()) == []


def test_delete_skill_md_forbidden_409(catalog_dir):
    _write_skill(catalog_dir, "good")

    with pytest.raises(HTTPException) as exc:
        skills.delete_skill_file("good", "SKILL.md", _mock_request())

    assert exc.value.status_code == 409


def test_delete_skill_file_ok(catalog_dir, audit_trail):
    skill_dir = _write_skill(catalog_dir, "good", extra={"references/doc.md": b"x\n"})

    result = skills.delete_skill_file("good", "references/doc.md", _mock_request())

    assert result["ok"] is True
    assert not (skill_dir / "references" / "doc.md").exists()
    assert [entry["action"] for entry in audit_trail] == ["delete"]
    assert audit_trail[0]["target_id"] == "good:references/doc.md"


def test_delete_skill_file_missing_404(catalog_dir):
    _write_skill(catalog_dir, "good")

    with pytest.raises(HTTPException) as exc:
        skills.delete_skill_file("good", "references/none.md", _mock_request())

    assert exc.value.status_code == 404


def test_delete_skill_file_through_symlinked_dir_422(catalog_dir, tmp_path):
    """删除路径经符号链接目录指向外部文件：422，外部文件完好。"""
    skill_dir = _write_skill(catalog_dir, "good")
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("keep me\n", encoding="utf-8")
    (skill_dir / "references").symlink_to(outside, target_is_directory=True)

    with pytest.raises(HTTPException) as exc:
        skills.delete_skill_file("good", "references/secret.txt", _mock_request())

    assert exc.value.status_code == 422
    assert secret.read_text(encoding="utf-8") == "keep me\n"


# ── 新建 / 删除 skill ──────────────────────────────────────────────


def test_create_skill_ok(catalog_dir, audit_trail):
    result = skills.create_skill(
        skills.SkillCreateBody(name="fresh", content=_skill_md("fresh")),
        _mock_request(),
    )

    assert result == {"name": "fresh"}
    assert (catalog_dir / "fresh" / "SKILL.md").exists()
    # B1：skill 内容树内无 .lock 残留（锁在 catalog 根）
    assert list((catalog_dir / "fresh").rglob("*.lock")) == []
    assert [entry["action"] for entry in audit_trail] == ["create"]
    assert audit_trail[0]["target_id"] == "fresh"


def test_create_skill_duplicate_409(catalog_dir):
    _write_skill(catalog_dir, "good")

    with pytest.raises(HTTPException) as exc:
        skills.create_skill(
            skills.SkillCreateBody(name="good", content=_skill_md("good")),
            _mock_request(),
        )

    assert exc.value.status_code == 409


def test_create_skill_invalid_name_422(catalog_dir):
    with pytest.raises(HTTPException) as exc:
        skills.create_skill(
            skills.SkillCreateBody(name="Bad_Name", content=_skill_md("bad")),
            _mock_request(),
        )

    assert exc.value.status_code == 422


def test_create_skill_invalid_content_400(catalog_dir):
    with pytest.raises(HTTPException) as exc:
        skills.create_skill(
            skills.SkillCreateBody(name="fresh", content="no frontmatter"),
            _mock_request(),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["diagnostics"]


def test_delete_skill_ok_removes_lock(catalog_dir, audit_trail):
    _write_skill(catalog_dir, "good")
    lock_file = catalog_dir / "good.lock"

    result = skills.delete_skill("good", _mock_request())

    assert result["ok"] is True
    assert not (catalog_dir / "good").exists()
    assert not lock_file.exists()
    assert [entry["action"] for entry in audit_trail] == ["delete"]
    assert audit_trail[0]["target_id"] == "good"


def test_delete_skill_missing_404(catalog_dir):
    with pytest.raises(HTTPException) as exc:
        skills.delete_skill("ghost", _mock_request())

    assert exc.value.status_code == 404


# ── 预置同步 ──────────────────────────────────────────────────────


def _setup_presets(catalog_dir: Path, example_dir: Path) -> None:
    _write_skill(example_dir, "p-current")
    _write_skill(catalog_dir, "p-current")
    _write_skill(example_dir, "p-diverged")
    _write_skill(catalog_dir, "p-diverged", extra={"local.txt": b"custom\n"})
    _write_skill(example_dir, "p-missing")
    # conflict：本地存在同名非目录项
    _write_skill(example_dir, "p-conflict")
    (catalog_dir / "p-conflict").write_text("not a dir", encoding="utf-8")


def test_presets_classification_and_labels(catalog_dir, example_dir):
    _setup_presets(catalog_dir, example_dir)
    _write_skill(catalog_dir, "local-only")

    result = skills.list_presets()

    rows = {row["name"]: row for row in result["presets"]}
    assert rows["p-current"]["state"] == "current"
    assert rows["p-diverged"]["state"] == "diverged"
    assert rows["p-missing"]["state"] == "missing"
    assert rows["p-conflict"]["state"] == "conflict"
    # label 与 preset_sync.STATE_LABELS 单一 owner 的映射关系（不断言整句文案）
    for row in result["presets"]:
        state = preset_sync.SyncState(row["state"])
        assert row["label"] == preset_sync.STATE_LABELS[state]
    assert result["local_only"] == ["local-only"]


def test_presets_apply_selective_names(catalog_dir, example_dir, audit_trail):
    _setup_presets(catalog_dir, example_dir)

    result = skills.apply_presets_route(
        skills.PresetApplyBody(names=["p-missing"]), _mock_request()
    )

    assert [outcome["name"] for outcome in result["outcomes"]] == ["p-missing"]
    assert result["outcomes"][0]["backup"] is None
    assert result["failures"] == []
    assert (catalog_dir / "p-missing" / "SKILL.md").exists()
    # 未选中的 diverged 项保持原样
    assert (catalog_dir / "p-diverged" / "local.txt").exists()
    assert [entry["action"] for entry in audit_trail] == ["sync"]
    assert audit_trail[0]["target_id"] == "p-missing"


def test_presets_apply_all_with_backup(catalog_dir, example_dir):
    _setup_presets(catalog_dir, example_dir)

    result = skills.apply_presets_route(skills.PresetApplyBody(), _mock_request())

    names = {outcome["name"] for outcome in result["outcomes"]}
    assert names == {"p-missing", "p-diverged"}
    diverged = next(o for o in result["outcomes"] if o["name"] == "p-diverged")
    backup = Path(diverged["backup"])
    assert backup.parent.name == preset_sync.BACKUP_CONTAINER_NAME
    assert (backup / "local.txt").exists()
    # 预置副本已覆盖生效目录
    assert not (catalog_dir / "p-diverged" / "local.txt").exists()
    # conflict 项不被触碰
    assert (catalog_dir / "p-conflict").is_file()


# ── 安装管线：inspect（本地 zip/folder）─────────────────────────────


def test_inspect_zip_multiple_candidates(catalog_dir, stash_dir):
    result = _inspect_zip({
        "skill-a/SKILL.md": _skill_md("skill-a").encode(),
        "skill-a/references/doc.md": b"# doc\n",
        "nested/skill-b/SKILL.md": _skill_md("skill-b").encode(),
        "nested/skill-b/scripts/run.sh": b"echo hi\n",
    })

    assert re.fullmatch(r"[A-Za-z0-9_-]{16,}", result["token"])
    candidates = {candidate["root"]: candidate for candidate in result["candidates"]}
    assert set(candidates) == {"skill-a", "nested/skill-b"}
    first = candidates["skill-a"]
    assert first["ok"] is True
    assert first["name"] == "skill-a"
    assert first["has_scripts"] is False
    assert first["file_count"] == 2
    assert first["conflict"] is False
    second = candidates["nested/skill-b"]
    assert second["has_scripts"] is True
    assert second["script_files"] == ["scripts/run.sh"]
    # stash 已落盘
    assert (stash_dir / result["token"] / "tree").is_dir()


def test_inspect_zip_marks_conflict(catalog_dir, stash_dir):
    _write_skill(catalog_dir, "skill-a")

    result = _inspect_zip({"vendor/SKILL.md": _skill_md("skill-a").encode()})

    assert result["candidates"][0]["conflict"] is True


def test_inspect_zip_bad_candidate_diagnostics(catalog_dir, stash_dir):
    result = _inspect_zip({"broken/SKILL.md": b"---\nname: broken\n---\n"})

    candidate = result["candidates"][0]
    assert candidate["ok"] is False
    assert candidate["name"] is None
    assert [d["kind"] for d in candidate["diagnostics"]] == ["description-missing"]


def test_inspect_zip_dangerous_entries_rejected(catalog_dir, stash_dir):
    # zip-slip
    with pytest.raises(HTTPException) as exc:
        _inspect_zip({"../evil.txt": b"x"})
    assert exc.value.status_code == 422
    # 绝对路径
    with pytest.raises(HTTPException) as exc:
        _inspect_zip({"/abs/path.txt": b"x"})
    assert exc.value.status_code == 422
    # 符号链接条目（external_attr 高位 unix mode）
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("link.sh")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/etc/passwd")
    with pytest.raises(HTTPException) as exc:
        skills.inspect_import(
            skills.ImportInspectBody(
                kind="zip", archive_b64=base64.b64encode(buffer.getvalue()).decode()
            )
        )
    assert exc.value.status_code == 422
    # 非法 base64
    with pytest.raises(HTTPException) as exc:
        skills.inspect_import(
            skills.ImportInspectBody(kind="zip", archive_b64="!!!not-base64!!!")
        )
    assert exc.value.status_code == 422


def test_inspect_zip_decoded_size_limit(catalog_dir, stash_dir, monkeypatch):
    """S1：解码后字节数过 _MAX_ARCHIVE_BYTES 显式 422（pydantic 卡 b64 字符数）。"""
    monkeypatch.setattr(skills, "_MAX_ARCHIVE_BYTES", 64)
    payload = _zip_b64({"s/SKILL.md": _skill_md("s").encode()})
    assert len(base64.b64decode(payload)) > 64

    with pytest.raises(HTTPException) as exc:
        skills.inspect_import(skills.ImportInspectBody(kind="zip", archive_b64=payload))

    assert exc.value.status_code == 422
    assert "16MiB" in exc.value.detail


def test_archive_b64_limit_matches_16mib_decoded():
    """b64 字符上限恰好放行 16MiB 解码字节（前端/文档口径）。"""
    assert skills._MAX_ARCHIVE_BYTES == 16 * 1024 * 1024
    assert skills._MAX_ARCHIVE_B64_CHARS == math.ceil(skills._MAX_ARCHIVE_BYTES / 3) * 4


def test_inspect_folder_manifest(catalog_dir, stash_dir):
    files = {
        "my-skill/SKILL.md": base64.b64encode(_skill_md("my-skill").encode()).decode(),
        "my-skill/scripts/run.sh": base64.b64encode(b"echo hi\n").decode(),
    }

    result = skills.inspect_import(
        skills.ImportInspectBody(kind="folder", files=files)
    )

    candidate = result["candidates"][0]
    assert candidate["root"] == "my-skill"
    assert candidate["ok"] is True
    assert candidate["has_scripts"] is True


def test_inspect_folder_traversal_rejected(catalog_dir, stash_dir):
    files = {"../evil.txt": base64.b64encode(b"x").decode()}

    with pytest.raises(HTTPException) as exc:
        skills.inspect_import(skills.ImportInspectBody(kind="folder", files=files))

    assert exc.value.status_code == 422


def test_folder_manifest_model_limits(monkeypatch):
    """S5：条数/单值/总长在 pydantic 请求模型层拒绝。"""
    monkeypatch.setattr(skill_import, "MAX_IMPORT_ENTRIES", 2)
    with pytest.raises(ValidationError):
        skills.ImportInspectBody(
            kind="folder", files={f"f{i}.txt": "eA==" for i in range(3)}
        )
    monkeypatch.setattr(skill_import, "MAX_IMPORT_ENTRIES", 500)
    monkeypatch.setattr(skills, "_MAX_FILE_B64_CHARS", 4)
    with pytest.raises(ValidationError):
        skills.ImportInspectBody(kind="folder", files={"a.txt": "eA" * 3})
    monkeypatch.setattr(skills, "_MAX_FILE_B64_CHARS", 2 * 1024 * 1024)
    monkeypatch.setattr(skills, "_MAX_ARCHIVE_B64_CHARS", 7)
    with pytest.raises(ValidationError):
        skills.ImportInspectBody(
            kind="folder", files={"a.txt": "eA==", "b.txt": "eA=="}
        )


def test_inspect_unknown_kind_422(catalog_dir, stash_dir):
    with pytest.raises(HTTPException) as exc:
        skills.inspect_import(skills.ImportInspectBody(kind="magic"))

    assert exc.value.status_code == 422


# ── 安装管线：confirm ──────────────────────────────────────────────


def test_confirm_installs_skill(catalog_dir, stash_dir, audit_trail):
    inspected = _inspect_zip({
        "vendor-dir/SKILL.md": _skill_md("real-name").encode(),
        "vendor-dir/references/doc.md": b"# doc\n",
    })

    result = skills.confirm_import(
        skills.ImportConfirmBody(token=inspected["token"], root="vendor-dir"),
        _mock_request(),
    )

    # 安装以 frontmatter name 建目录，第三方原目录名不参与
    assert result == {"name": "real-name", "backup": None}
    assert (catalog_dir / "real-name" / "SKILL.md").exists()
    assert (catalog_dir / "real-name" / "references" / "doc.md").exists()
    assert not (catalog_dir / "vendor-dir").exists()
    # confirm 用后即删
    assert not (stash_dir / inspected["token"]).exists()
    assert [entry["action"] for entry in audit_trail] == ["install"]
    assert audit_trail[0]["target_id"] == "real-name"


def test_confirm_conflict_409_then_overwrite_backup(catalog_dir, stash_dir):
    _write_skill(catalog_dir, "real-name", extra={"local.txt": b"custom\n"})
    inspected = _inspect_zip({"vendor/SKILL.md": _skill_md("real-name").encode()})

    with pytest.raises(HTTPException) as exc:
        skills.confirm_import(
            skills.ImportConfirmBody(token=inspected["token"], root="vendor"),
            _mock_request(),
        )
    assert exc.value.status_code == 409
    # 409 后 stash 保留，可用 overwrite 重试
    result = skills.confirm_import(
        skills.ImportConfirmBody(
            token=inspected["token"], root="vendor", overwrite=True
        ),
        _mock_request(),
    )

    assert result["name"] == "real-name"
    backup = Path(result["backup"])
    assert backup.parent.name == preset_sync.BACKUP_CONTAINER_NAME
    assert (backup / "local.txt").exists()
    assert not (catalog_dir / "real-name" / "local.txt").exists()


def test_confirm_unknown_token_404(catalog_dir, stash_dir):
    with pytest.raises(HTTPException) as exc:
        skills.confirm_import(
            skills.ImportConfirmBody(token="no-such-token", root=""),
            _mock_request(),
        )

    assert exc.value.status_code == 404


def test_confirm_invalid_candidate_422(catalog_dir, stash_dir):
    inspected = _inspect_zip({"broken/SKILL.md": b"---\nname: broken\n---\n"})

    with pytest.raises(HTTPException) as exc:
        skills.confirm_import(
            skills.ImportConfirmBody(token=inspected["token"], root="broken"),
            _mock_request(),
        )

    assert exc.value.status_code == 422


# ── GitHub inspect 路由（下载以替身覆盖）─────────────────────────────


def _patch_download(monkeypatch, archive: bytes):
    monkeypatch.setattr(
        skills.skill_import_github, "download_github_zip", lambda target: archive
    )


def test_github_inspect_route_success(catalog_dir, stash_dir, monkeypatch):
    archive = _make_zip({
        "repo-main/skills/foo/SKILL.md": _skill_md("foo").encode(),
        "repo-main/skills/bar/SKILL.md": _skill_md("bar").encode(),
    })
    _patch_download(monkeypatch, archive)

    result = skills.inspect_github_import(
        skills.GithubInspectBody(url="https://github.com/o/r/tree/main/skills/foo")
    )

    # subpath 过滤提前到 ingest：候选只有子树内的 foo
    assert [candidate["name"] for candidate in result["candidates"]] == ["foo"]
    assert result["candidates"][0]["root"] == "repo-main/skills/foo"


def test_github_inspect_subpath_prefilters_at_ingest(
    catalog_dir, stash_dir, monkeypatch
):
    """monorepo 场景：树外条目不触发条目数护栏（小上限替身）。"""
    monkeypatch.setattr(skill_import, "MAX_IMPORT_ENTRIES", 5)
    files = {f"repo-main/bulk/file-{i}.txt": b"x" for i in range(20)}
    files["repo-main/skills/foo/SKILL.md"] = _skill_md("foo").encode()
    files["repo-main/skills/foo/scripts/run.sh"] = b"echo hi\n"
    _patch_download(monkeypatch, _make_zip(files))

    result = skills.inspect_github_import(
        skills.GithubInspectBody(url="https://github.com/o/r/tree/main/skills/foo")
    )

    assert [candidate["name"] for candidate in result["candidates"]] == ["foo"]
    candidate = result["candidates"][0]
    assert candidate["file_count"] == 2
    assert candidate["has_scripts"] is True
    # confirm 链路不受影响：root 语义仍是归档内相对路径
    installed = skills.confirm_import(
        skills.ImportConfirmBody(token=result["token"], root=candidate["root"]),
        _mock_request(),
    )
    assert installed["name"] == "foo"
    assert (catalog_dir / "foo" / "scripts" / "run.sh").exists()


def test_github_inspect_subpath_without_skill_md_422(
    catalog_dir, stash_dir, monkeypatch
):
    archive = _make_zip({"repo-main/other/SKILL.md": _skill_md("other").encode()})
    _patch_download(monkeypatch, archive)

    with pytest.raises(HTTPException) as exc:
        skills.inspect_github_import(
            skills.GithubInspectBody(url="https://github.com/o/r/tree/main/skills/foo")
        )

    assert exc.value.status_code == 422
    assert "no SKILL.md" in exc.value.detail
    assert "skills/foo" in exc.value.detail


def test_github_inspect_no_skill_md_422(catalog_dir, stash_dir, monkeypatch):
    archive = _make_zip({"repo-main/README.md": b"hi\n"})
    _patch_download(monkeypatch, archive)

    with pytest.raises(HTTPException) as exc:
        skills.inspect_github_import(
            skills.GithubInspectBody(url="https://github.com/o/r")
        )

    assert exc.value.status_code == 422
    assert "no SKILL.md" in exc.value.detail


def test_github_inspect_limit_guidance_without_subpath(
    catalog_dir, stash_dir, monkeypatch
):
    monkeypatch.setattr(skill_import, "MAX_IMPORT_ENTRIES", 5)
    archive = _make_zip({f"repo-main/f{i}.txt": b"x" for i in range(6)})
    _patch_download(monkeypatch, archive)

    with pytest.raises(HTTPException) as exc:
        skills.inspect_github_import(
            skills.GithubInspectBody(url="https://github.com/o/r")
        )

    assert exc.value.status_code == 422
    assert "/tree/<ref>/<subdirectory>" in exc.value.detail


def test_github_inspect_limit_no_guidance_with_subpath(
    catalog_dir, stash_dir, monkeypatch
):
    monkeypatch.setattr(skill_import, "MAX_IMPORT_ENTRIES", 3)
    files = {f"repo-main/skills/foo/f{i}.txt": b"x" for i in range(4)}
    files["repo-main/skills/foo/SKILL.md"] = _skill_md("foo").encode()
    _patch_download(monkeypatch, _make_zip(files))

    with pytest.raises(HTTPException) as exc:
        skills.inspect_github_import(
            skills.GithubInspectBody(url="https://github.com/o/r/tree/main/skills/foo")
        )

    # 子树自身超限时按原样报 422，不追加 subpath 引导（用户已在用 subpath）
    assert exc.value.status_code == 422
    assert "/tree/<ref>/" not in exc.value.detail


def test_github_inspect_invalid_url_422(catalog_dir, stash_dir):
    with pytest.raises(HTTPException) as exc:
        skills.inspect_github_import(
            skills.GithubInspectBody(url="https://evil.com/o/r")
        )

    assert exc.value.status_code == 422


# ── 生效目录解析 ────────────────────────────────────────────────────


def test_effective_catalog_dir_reads_llm_toml(monkeypatch, tmp_path):
    custom = tmp_path / "custom-skills"
    config = tmp_path / "llm.toml"
    config.write_text(f'[skills]\ncatalog_dir = "{custom}"\n', encoding="utf-8")
    monkeypatch.setattr(skills, "_LLM_CONFIG_PATH", config)

    assert _effective_catalog_dir() == custom


def test_effective_catalog_dir_fallbacks(monkeypatch, tmp_path):
    # 文件缺失
    monkeypatch.setattr(skills, "_LLM_CONFIG_PATH", tmp_path / "missing.toml")
    assert _effective_catalog_dir() == SKILLS_DIR
    # 键缺失
    config = tmp_path / "llm.toml"
    config.write_text("[runtime]\nenabled = true\n", encoding="utf-8")
    monkeypatch.setattr(skills, "_LLM_CONFIG_PATH", config)
    assert _effective_catalog_dir() == SKILLS_DIR
    # 非字符串
    config.write_text("[skills]\ncatalog_dir = 123\n", encoding="utf-8")
    assert _effective_catalog_dir() == SKILLS_DIR
    # TOML 解析失败
    config.write_text("not [valid toml", encoding="utf-8")
    assert _effective_catalog_dir() == SKILLS_DIR
