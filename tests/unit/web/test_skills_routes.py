import base64
import io
import json
import stat
import time
import types
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException

import httpx  # noqa: E402

from quickquip.app.web import skill_import  # noqa: E402
from quickquip.app.web.routes import skills  # noqa: E402
from quickquip.llm.skills import preset_sync  # noqa: E402


def _mock_request():
    req = MagicMock()
    req.client.host = "127.0.0.1"
    return req


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    monkeypatch.setattr(skills.audit_logger, "log", lambda *args, **kwargs: None)


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
    missing = items["no-skill-md"]
    assert missing["ok"] is False
    assert missing["diagnostics"][0]["kind"] == "missing-skill-file"
    bad = items["bad-parse"]
    assert bad["ok"] is False
    assert any(d["kind"] == "name-directory-mismatch" for d in bad["diagnostics"])


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
    assert any(
        d["kind"] == "name-directory-mismatch" for d in exc.value.detail["diagnostics"]
    )


def test_write_skill_file_upsert_atomic(catalog_dir, monkeypatch):
    skill_dir = _write_skill(catalog_dir, "good")
    audits: list[dict] = []
    monkeypatch.setattr(
        skills.audit_logger,
        "log",
        lambda request, **kwargs: audits.append(kwargs),
    )

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
    assert [entry["action"] for entry in audits] == ["create", "update"]
    assert audits[0]["target_id"] == "good:references/new.md"


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


def test_delete_skill_md_forbidden_409(catalog_dir):
    _write_skill(catalog_dir, "good")

    with pytest.raises(HTTPException) as exc:
        skills.delete_skill_file("good", "SKILL.md", _mock_request())

    assert exc.value.status_code == 409


def test_delete_skill_file_ok(catalog_dir):
    skill_dir = _write_skill(catalog_dir, "good", extra={"references/doc.md": b"x\n"})

    result = skills.delete_skill_file("good", "references/doc.md", _mock_request())

    assert result["ok"] is True
    assert not (skill_dir / "references" / "doc.md").exists()


def test_delete_skill_file_missing_404(catalog_dir):
    _write_skill(catalog_dir, "good")

    with pytest.raises(HTTPException) as exc:
        skills.delete_skill_file("good", "references/none.md", _mock_request())

    assert exc.value.status_code == 404


# ── 新建 / 删除 skill ──────────────────────────────────────────────


def test_create_skill_ok(catalog_dir):
    result = skills.create_skill(
        skills.SkillCreateBody(name="fresh", content=_skill_md("fresh")),
        _mock_request(),
    )

    assert result == {"name": "fresh"}
    assert (catalog_dir / "fresh" / "SKILL.md").exists()


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


def test_delete_skill_ok(catalog_dir):
    _write_skill(catalog_dir, "good")

    result = skills.delete_skill("good", _mock_request())

    assert result["ok"] is True
    assert not (catalog_dir / "good").exists()


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
    assert rows["p-current"]["label"] == "已安装，与预置副本一致"
    assert rows["p-diverged"]["state"] == "diverged"
    assert rows["p-diverged"]["label"] == "已安装，与预置副本不同"
    assert rows["p-missing"]["state"] == "missing"
    assert rows["p-missing"]["label"] == "未安装"
    assert rows["p-conflict"]["state"] == "conflict"
    assert rows["p-conflict"]["label"] == "存在同名非目录项，需人工处理"
    assert result["local_only"] == ["local-only"]


def test_presets_apply_selective_names(catalog_dir, example_dir):
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


# ── 安装管线：inspect ─────────────────────────────────────────────


def test_inspect_zip_multiple_candidates(catalog_dir, stash_dir):
    payload = _zip_b64({
        "skill-a/SKILL.md": _skill_md("skill-a").encode(),
        "skill-a/references/doc.md": b"# doc\n",
        "nested/skill-b/SKILL.md": _skill_md("skill-b").encode(),
        "nested/skill-b/scripts/run.sh": b"echo hi\n",
    })

    result = skills.inspect_import(
        skills.ImportInspectBody(kind="zip", archive_b64=payload)
    )

    assert result["token"]
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
    payload = _zip_b64({"skill-a/SKILL.md": _skill_md("skill-a").encode()})

    result = skills.inspect_import(
        skills.ImportInspectBody(kind="zip", archive_b64=payload)
    )

    assert result["candidates"][0]["conflict"] is True


def test_inspect_zip_bad_candidate_diagnostics(catalog_dir, stash_dir):
    payload = _zip_b64({"broken/SKILL.md": b"---\nname: broken\n---\n"})

    result = skills.inspect_import(
        skills.ImportInspectBody(kind="zip", archive_b64=payload)
    )

    candidate = result["candidates"][0]
    assert candidate["ok"] is False
    assert candidate["name"] is None
    assert candidate["diagnostics"]


def test_inspect_zip_slip_entry_rejected(catalog_dir, stash_dir):
    payload = _zip_b64({"../evil.txt": b"x"})

    with pytest.raises(HTTPException) as exc:
        skills.inspect_import(skills.ImportInspectBody(kind="zip", archive_b64=payload))

    assert exc.value.status_code == 422


def test_inspect_zip_absolute_entry_rejected(catalog_dir, stash_dir):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("/abs/path.txt", b"x")
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")

    with pytest.raises(HTTPException) as exc:
        skills.inspect_import(skills.ImportInspectBody(kind="zip", archive_b64=payload))

    assert exc.value.status_code == 422


def test_inspect_zip_symlink_entry_rejected(catalog_dir, stash_dir):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("link.sh")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/etc/passwd")
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")

    with pytest.raises(HTTPException) as exc:
        skills.inspect_import(skills.ImportInspectBody(kind="zip", archive_b64=payload))

    assert exc.value.status_code == 422


def test_inspect_zip_invalid_base64_422(catalog_dir, stash_dir):
    with pytest.raises(HTTPException) as exc:
        skills.inspect_import(
            skills.ImportInspectBody(kind="zip", archive_b64="!!!not-base64!!!")
        )

    assert exc.value.status_code == 422


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


def test_inspect_unknown_kind_422(catalog_dir, stash_dir):
    with pytest.raises(HTTPException) as exc:
        skills.inspect_import(skills.ImportInspectBody(kind="magic"))

    assert exc.value.status_code == 422


# ── 安装管线：confirm 与 stash ─────────────────────────────────────


def _inspect_zip(catalog_dir, stash_dir, files: dict[str, bytes]) -> dict:
    return skills.inspect_import(
        skills.ImportInspectBody(kind="zip", archive_b64=_zip_b64(files))
    )


def test_confirm_installs_skill(catalog_dir, stash_dir):
    inspected = _inspect_zip(catalog_dir, stash_dir, {
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


def test_confirm_conflict_409_then_overwrite_backup(catalog_dir, stash_dir):
    _write_skill(catalog_dir, "real-name", extra={"local.txt": b"custom\n"})
    inspected = _inspect_zip(
        catalog_dir, stash_dir, {"vendor/SKILL.md": _skill_md("real-name").encode()}
    )

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
    inspected = _inspect_zip(
        catalog_dir, stash_dir, {"broken/SKILL.md": b"---\nname: broken\n---\n"}
    )

    with pytest.raises(HTTPException) as exc:
        skills.confirm_import(
            skills.ImportConfirmBody(token=inspected["token"], root="broken"),
            _mock_request(),
        )

    assert exc.value.status_code == 422


def test_stash_expired_cleanup_on_inspect(catalog_dir, stash_dir):
    stash_dir.mkdir(parents=True)
    stale = stash_dir / "old-token"
    (stale / "tree").mkdir(parents=True)
    (stale / "meta.json").write_text(
        json.dumps({"created_at": time.time() - 3600}), encoding="utf-8"
    )
    fresh = stash_dir / "fresh-token"
    (fresh / "tree").mkdir(parents=True)
    (fresh / "meta.json").write_text(
        json.dumps({"created_at": time.time()}), encoding="utf-8"
    )

    _inspect_zip(catalog_dir, stash_dir, {"s/SKILL.md": _skill_md("s").encode()})

    assert not stale.exists()
    assert fresh.exists()


# ── GitHub 导入 ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://github.com/owner/repo",
            skill_import.GithubTarget(owner="owner", repo="repo"),
        ),
        (
            "https://github.com/owner/repo/",
            skill_import.GithubTarget(owner="owner", repo="repo"),
        ),
        (
            "https://github.com/owner/repo/tree/main",
            skill_import.GithubTarget(owner="owner", repo="repo", ref="main"),
        ),
        (
            "https://github.com/owner/repo/tree/v1.0/skills/foo",
            skill_import.GithubTarget(
                owner="owner", repo="repo", ref="v1.0", subpath="skills/foo"
            ),
        ),
        (
            "https://github.com/owner/repo.git",
            skill_import.GithubTarget(owner="owner", repo="repo"),
        ),
    ],
)
def test_parse_github_url_valid(url, expected):
    assert skill_import.parse_github_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/repo/blob/main/SKILL.md",
        "https://evil.com/owner/repo",
        "http://github.com/owner/repo",
        "https://github.com/only-owner",
        "https://github.com/owner/repo/releases",
        "https://github.com/ow ner/repo",
    ],
)
def test_parse_github_url_rejected(url):
    with pytest.raises(HTTPException) as exc:
        skill_import.parse_github_url(url)
    assert exc.value.status_code == 422


class _FakeStreamResponse:
    def __init__(self, *, status_code: int = 200, chunks=(), redirect: bool = False):
        self.status_code = status_code
        self._chunks = list(chunks)
        self._redirect = redirect

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def is_redirect(self):
        return self._redirect

    def iter_bytes(self):
        yield from self._chunks


class _FakeClient:
    def __init__(self, *, response=None, error=None):
        self._response = response
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def stream(self, method, url):
        if self._error is not None:
            raise self._error
        return self._response


def _patch_httpx(monkeypatch, client: _FakeClient):
    fake = types.SimpleNamespace(
        Client=lambda *args, **kwargs: client,
        TimeoutException=httpx.TimeoutException,
        HTTPError=httpx.HTTPError,
    )
    monkeypatch.setattr(skill_import, "httpx", fake)


def test_github_download_success(monkeypatch):
    _patch_httpx(
        monkeypatch,
        _FakeClient(response=_FakeStreamResponse(chunks=[b"ab", b"cd"])),
    )

    data = skill_import.download_github_zip(
        skill_import.GithubTarget(owner="o", repo="r", ref="main")
    )

    assert data == b"abcd"


def test_github_download_timeout_502(monkeypatch):
    _patch_httpx(
        monkeypatch,
        _FakeClient(error=httpx.TimeoutException("boom")),
    )

    with pytest.raises(HTTPException) as exc:
        skill_import.download_github_zip(skill_import.GithubTarget(owner="o", repo="r"))

    assert exc.value.status_code == 502
    assert "timed out" in exc.value.detail


def test_github_download_not_found_502(monkeypatch):
    _patch_httpx(
        monkeypatch,
        _FakeClient(response=_FakeStreamResponse(status_code=404)),
    )

    with pytest.raises(HTTPException) as exc:
        skill_import.download_github_zip(skill_import.GithubTarget(owner="o", repo="r"))

    assert exc.value.status_code == 502
    assert "not found" in exc.value.detail


def test_github_download_oversize_422(monkeypatch):
    oversized = b"x" * (skill_import.MAX_IMPORT_TOTAL_BYTES + 1)
    _patch_httpx(
        monkeypatch,
        _FakeClient(response=_FakeStreamResponse(chunks=[oversized])),
    )

    with pytest.raises(HTTPException) as exc:
        skill_import.download_github_zip(skill_import.GithubTarget(owner="o", repo="r"))

    assert exc.value.status_code == 422


def test_github_inspect_route_success(catalog_dir, stash_dir, monkeypatch):
    archive = _make_zip({
        "repo-main/skills/foo/SKILL.md": _skill_md("foo").encode(),
        "repo-main/skills/bar/SKILL.md": _skill_md("bar").encode(),
    })
    monkeypatch.setattr(
        skills.skill_import, "download_github_zip", lambda target: archive
    )

    result = skills.inspect_github_import(
        skills.GithubInspectBody(url="https://github.com/o/r/tree/main/skills/foo")
    )

    # subpath 收窄到匹配候选
    assert [candidate["name"] for candidate in result["candidates"]] == ["foo"]
    assert result["candidates"][0]["root"] == "repo-main/skills/foo"


def test_github_inspect_no_skill_md_422(catalog_dir, stash_dir, monkeypatch):
    archive = _make_zip({"repo-main/README.md": b"hi\n"})
    monkeypatch.setattr(
        skills.skill_import, "download_github_zip", lambda target: archive
    )

    with pytest.raises(HTTPException) as exc:
        skills.inspect_github_import(
            skills.GithubInspectBody(url="https://github.com/o/r")
        )

    assert exc.value.status_code == 422
    assert "no SKILL.md" in exc.value.detail


def test_ingest_zip_scope_drops_outside_entries_before_guardrails():
    files = {f"repo-main/bulk/file-{i}.txt": b"x" for i in range(600)}
    # 树外超限文件与符号链接同样直接丢弃，不做校验、不计入上限
    files["repo-main/bulk/big.bin"] = b"y" * (2 * 1024 * 1024)
    files["repo-main/skills/foo/SKILL.md"] = _skill_md("foo").encode()
    files["repo-main/skills/foo/references/doc.md"] = b"# doc\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
        info = zipfile.ZipInfo("repo-main/bulk/link.sh")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/etc/passwd")

    entries = skill_import.ingest_zip_bytes(buffer.getvalue(), scope="skills/foo")

    assert {entry.path for entry in entries} == {
        "repo-main/skills/foo/SKILL.md",
        "repo-main/skills/foo/references/doc.md",
    }


def test_ingest_zip_without_scope_entry_limit_unchanged():
    files = {f"pkg/file-{i}.txt": b"x" for i in range(501)}

    with pytest.raises(HTTPException) as exc:
        skill_import.ingest_zip_bytes(_make_zip(files))

    assert exc.value.status_code == 422
    assert "/tree/<ref>/" not in exc.value.detail


def test_github_inspect_subpath_prefilters_at_ingest(
    catalog_dir, stash_dir, monkeypatch
):
    files = {f"repo-main/bulk/file-{i}.txt": b"x" for i in range(600)}
    files["repo-main/skills/foo/SKILL.md"] = _skill_md("foo").encode()
    files["repo-main/skills/foo/scripts/run.sh"] = b"echo hi\n"
    archive = _make_zip(files)
    monkeypatch.setattr(
        skills.skill_import, "download_github_zip", lambda target: archive
    )

    result = skills.inspect_github_import(
        skills.GithubInspectBody(url="https://github.com/o/r/tree/main/skills/foo")
    )

    # 600 个树外条目没有触发 500 条目上限；候选只含子树内的 foo
    assert [candidate["name"] for candidate in result["candidates"]] == ["foo"]
    candidate = result["candidates"][0]
    assert candidate["root"] == "repo-main/skills/foo"
    assert candidate["file_count"] == 2
    assert candidate["has_scripts"] is True
    # confirm 链路不受影响：root 语义仍是归档内相对路径
    installed = skills.confirm_import(
        skills.ImportConfirmBody(
            token=result["token"], root=candidate["root"]
        ),
        _mock_request(),
    )
    assert installed["name"] == "foo"
    assert (catalog_dir / "foo" / "scripts" / "run.sh").exists()


def test_github_inspect_subpath_without_skill_md_422(
    catalog_dir, stash_dir, monkeypatch
):
    archive = _make_zip({"repo-main/other/SKILL.md": _skill_md("other").encode()})
    monkeypatch.setattr(
        skills.skill_import, "download_github_zip", lambda target: archive
    )

    with pytest.raises(HTTPException) as exc:
        skills.inspect_github_import(
            skills.GithubInspectBody(url="https://github.com/o/r/tree/main/skills/foo")
        )

    assert exc.value.status_code == 422
    assert "no SKILL.md" in exc.value.detail
    assert "skills/foo" in exc.value.detail


def test_github_inspect_limit_guidance_without_subpath(
    catalog_dir, stash_dir, monkeypatch
):
    archive = _make_zip({f"repo-main/f{i}.txt": b"x" for i in range(501)})
    monkeypatch.setattr(
        skills.skill_import, "download_github_zip", lambda target: archive
    )

    with pytest.raises(HTTPException) as exc:
        skills.inspect_github_import(
            skills.GithubInspectBody(url="https://github.com/o/r")
        )

    assert exc.value.status_code == 422
    assert "/tree/<ref>/<subdirectory>" in exc.value.detail


def test_github_inspect_limit_no_guidance_with_subpath(
    catalog_dir, stash_dir, monkeypatch
):
    files = {f"repo-main/skills/foo/f{i}.txt": b"x" for i in range(501)}
    files["repo-main/skills/foo/SKILL.md"] = _skill_md("foo").encode()
    archive = _make_zip(files)
    monkeypatch.setattr(
        skills.skill_import, "download_github_zip", lambda target: archive
    )

    with pytest.raises(HTTPException) as exc:
        skills.inspect_github_import(
            skills.GithubInspectBody(url="https://github.com/o/r/tree/main/skills/foo")
        )

    # 子树自身超限时按原样报 422，不追加 subpath 引导（用户已在用 subpath）
    assert exc.value.status_code == 422
    assert "/tree/<ref>/" not in exc.value.detail


# ── 删除清理 ──────────────────────────────────────────────────────


def test_delete_skill_removes_lock_file(catalog_dir):
    _write_skill(catalog_dir, "good")
    lock_file = catalog_dir / "good.lock"

    skills.delete_skill("good", _mock_request())

    assert not (catalog_dir / "good").exists()
    assert not lock_file.exists()


# ── 生效目录解析 ────────────────────────────────────────────────────


def test_effective_catalog_dir_reads_llm_toml(monkeypatch, tmp_path):
    custom = tmp_path / "custom-skills"
    config = tmp_path / "llm.toml"
    config.write_text(f'[skills]\ncatalog_dir = "{custom}"\n', encoding="utf-8")
    monkeypatch.setattr(skills, "_LLM_CONFIG_PATH", config)

    from quickquip.app.web.routes.skills import _effective_catalog_dir

    assert _effective_catalog_dir() == custom


def test_effective_catalog_dir_fallbacks(monkeypatch, tmp_path):
    from quickquip.app.web.routes.skills import _effective_catalog_dir
    from quickquip.common.paths import SKILLS_DIR

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
