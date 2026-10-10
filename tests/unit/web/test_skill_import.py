"""skill_import / skill_import_stash / skill_import_github 管线级单测。

路由层端点用例在 test_skills_routes.py；本文件收编摄取护栏、候选发现、
stash 生命周期、安装落盘与 GitHub URL/下载（httpx 替身）的直接测试。
"""

import base64
import io
import json
import os
import stat
import time
import types
import zipfile

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException

import httpx  # noqa: E402

from quickquip.app.web import (  # noqa: E402
    skill_import,
    skill_import_github,
    skill_import_stash,
)


def _skill_md(name: str, description: str = "A test skill") -> bytes:
    return f"---\nname: {name}\ndescription: {description}\n---\n\nBody text.\n".encode()


def _make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return buffer.getvalue()


def _make_zip_with_symlink(link_name: str, files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
        info = zipfile.ZipInfo(link_name)
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# ── GitHub URL 解析（纯函数）────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://github.com/owner/repo",
            skill_import_github.GithubTarget(owner="owner", repo="repo"),
        ),
        (
            "https://github.com/owner/repo/",
            skill_import_github.GithubTarget(owner="owner", repo="repo"),
        ),
        (
            "https://github.com/owner/repo/tree/main",
            skill_import_github.GithubTarget(owner="owner", repo="repo", ref="main"),
        ),
        (
            "https://github.com/owner/repo/tree/v1.0/skills/foo",
            skill_import_github.GithubTarget(
                owner="owner", repo="repo", ref="v1.0", subpath="skills/foo"
            ),
        ),
        (
            "https://github.com/owner/repo.git",
            skill_import_github.GithubTarget(owner="owner", repo="repo"),
        ),
    ],
)
def test_parse_github_url_valid(url, expected):
    assert skill_import_github.parse_github_url(url) == expected


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
        skill_import_github.parse_github_url(url)
    assert exc.value.status_code == 422


# ── GitHub 下载（httpx 替身）─────────────────────────────────────────


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
    monkeypatch.setattr(skill_import_github, "httpx", fake)


def test_github_download_success(monkeypatch):
    _patch_httpx(
        monkeypatch,
        _FakeClient(response=_FakeStreamResponse(chunks=[b"ab", b"cd"])),
    )

    data = skill_import_github.download_github_zip(
        skill_import_github.GithubTarget(owner="o", repo="r", ref="main")
    )

    assert data == b"abcd"


def test_github_download_timeout_502(monkeypatch):
    _patch_httpx(monkeypatch, _FakeClient(error=httpx.TimeoutException("boom")))

    with pytest.raises(HTTPException) as exc:
        skill_import_github.download_github_zip(
            skill_import_github.GithubTarget(owner="o", repo="r")
        )

    assert exc.value.status_code == 502
    assert "timed out" in exc.value.detail


def test_github_download_not_found_502(monkeypatch):
    _patch_httpx(monkeypatch, _FakeClient(response=_FakeStreamResponse(status_code=404)))

    with pytest.raises(HTTPException) as exc:
        skill_import_github.download_github_zip(
            skill_import_github.GithubTarget(owner="o", repo="r")
        )

    assert exc.value.status_code == 502
    assert "not found" in exc.value.detail


def test_github_download_redirect_502(monkeypatch):
    """不跟随重定向：3xx 一律拒绝（宿主不会被诱导访问其他域名）。"""
    _patch_httpx(monkeypatch, _FakeClient(response=_FakeStreamResponse(redirect=True)))

    with pytest.raises(HTTPException) as exc:
        skill_import_github.download_github_zip(
            skill_import_github.GithubTarget(owner="o", repo="r")
        )

    assert exc.value.status_code == 502
    assert "redirect" in exc.value.detail


def test_github_download_oversize_422(monkeypatch):
    monkeypatch.setattr(skill_import_github, "MAX_IMPORT_TOTAL_BYTES", 10)
    _patch_httpx(
        monkeypatch,
        _FakeClient(response=_FakeStreamResponse(chunks=[b"x" * 11])),
    )

    with pytest.raises(HTTPException) as exc:
        skill_import_github.download_github_zip(
            skill_import_github.GithubTarget(owner="o", repo="r")
        )

    assert exc.value.status_code == 422
    assert "download limit" in exc.value.detail


# ── zip 摄取护栏 ────────────────────────────────────────────────────


def test_decode_zip_b64_invalid_422():
    with pytest.raises(HTTPException) as exc:
        skill_import.decode_zip_b64("!!!not-base64!!!")
    assert exc.value.status_code == 422


def test_ingest_zip_not_a_zip_422():
    with pytest.raises(HTTPException) as exc:
        skill_import.ingest_zip_bytes(b"definitely not a zip")
    assert exc.value.status_code == 422


def test_ingest_zip_slip_entry_rejected():
    with pytest.raises(HTTPException) as exc:
        skill_import.ingest_zip_bytes(_make_zip({"../evil.txt": b"x"}))
    assert exc.value.status_code == 422


def test_ingest_zip_absolute_entry_rejected():
    with pytest.raises(HTTPException) as exc:
        skill_import.ingest_zip_bytes(_make_zip({"/abs/path.txt": b"x"}))
    assert exc.value.status_code == 422


def test_ingest_zip_drive_letter_entry_rejected():
    """盘符相对路径（C:evil.txt）同样拒绝：Windows 下可逃逸出根。"""
    with pytest.raises(HTTPException) as exc:
        skill_import.ingest_zip_bytes(_make_zip({"C:evil.txt": b"x"}))
    assert exc.value.status_code == 422


def test_ingest_zip_symlink_entry_rejected():
    payload = _make_zip_with_symlink("link.sh", {"ok/SKILL.md": _skill_md("ok")})
    with pytest.raises(HTTPException) as exc:
        skill_import.ingest_zip_bytes(payload)
    assert exc.value.status_code == 422


def test_ingest_zip_entry_count_limit(monkeypatch):
    monkeypatch.setattr(skill_import, "MAX_IMPORT_ENTRIES", 5)
    files = {f"pkg/file-{i}.txt": b"x" for i in range(6)}

    with pytest.raises(skill_import.IngestLimitError) as exc:
        skill_import.ingest_zip_bytes(_make_zip(files))

    assert exc.value.status_code == 422
    assert "entries" in exc.value.detail


def test_ingest_zip_total_bytes_limit(monkeypatch):
    monkeypatch.setattr(skill_import, "MAX_IMPORT_TOTAL_BYTES", 10)
    monkeypatch.setattr(skill_import, "MAX_IMPORT_FILE_BYTES", 1024)
    files = {"a.bin": b"x" * 8, "b.bin": b"y" * 8}

    with pytest.raises(skill_import.IngestLimitError) as exc:
        skill_import.ingest_zip_bytes(_make_zip(files))

    assert exc.value.status_code == 422
    assert "total limit" in exc.value.detail


def test_ingest_zip_per_file_limit(monkeypatch):
    monkeypatch.setattr(skill_import, "MAX_IMPORT_FILE_BYTES", 4)

    with pytest.raises(HTTPException) as exc:
        skill_import.ingest_zip_bytes(_make_zip({"big.bin": b"x" * 5}))

    assert exc.value.status_code == 422
    assert "per-file limit" in exc.value.detail


def test_ingest_zip_scope_drops_outside_entries_before_guardrails(monkeypatch):
    """monorepo 场景：树外条目（含超限文件与符号链接）不过校验、不计上限。"""
    monkeypatch.setattr(skill_import, "MAX_IMPORT_ENTRIES", 5)
    files = {f"repo-main/bulk/file-{i}.txt": b"x" for i in range(20)}
    files["repo-main/bulk/big.bin"] = b"y" * (2 * 1024 * 1024)
    files["repo-main/skills/foo/SKILL.md"] = _skill_md("foo")
    files["repo-main/skills/foo/references/doc.md"] = b"# doc\n"
    payload = _make_zip_with_symlink("repo-main/bulk/link.sh", files)

    entries = skill_import.ingest_zip_bytes(payload, scope="skills/foo")

    assert {entry.path for entry in entries} == {
        "repo-main/skills/foo/SKILL.md",
        "repo-main/skills/foo/references/doc.md",
    }


def test_ingest_zip_scope_subtree_still_limited(monkeypatch):
    """scope 收窄后子树自身超限依旧拒绝。"""
    monkeypatch.setattr(skill_import, "MAX_IMPORT_ENTRIES", 3)
    files = {f"repo-main/skills/foo/f{i}.txt": b"x" for i in range(3)}
    files["repo-main/skills/foo/SKILL.md"] = _skill_md("foo")

    with pytest.raises(skill_import.IngestLimitError):
        skill_import.ingest_zip_bytes(_make_zip(files), scope="skills/foo")


# ── folder manifest 摄取 ────────────────────────────────────────────


def test_ingest_folder_ok():
    entries = skill_import.ingest_folder({
        "my-skill/SKILL.md": _b64(_skill_md("my-skill")),
        "my-skill/scripts/run.sh": _b64(b"echo hi\n"),
    })

    assert {entry.path for entry in entries} == {
        "my-skill/SKILL.md",
        "my-skill/scripts/run.sh",
    }


def test_ingest_folder_drive_letter_rejected():
    with pytest.raises(HTTPException) as exc:
        skill_import.ingest_folder({"C:evil.txt": _b64(b"x")})
    assert exc.value.status_code == 422


def test_ingest_folder_invalid_base64_422():
    with pytest.raises(HTTPException) as exc:
        skill_import.ingest_folder({"a/x.txt": "!!!"})
    assert exc.value.status_code == 422


def test_ingest_folder_count_limit(monkeypatch):
    monkeypatch.setattr(skill_import, "MAX_IMPORT_ENTRIES", 2)
    files = {f"f{i}.txt": _b64(b"x") for i in range(3)}

    with pytest.raises(HTTPException) as exc:
        skill_import.ingest_folder(files)

    assert exc.value.status_code == 422


# ── 候选发现 ────────────────────────────────────────────────────────


def test_discover_candidates_multiple_and_scripts(tmp_path):
    entries = skill_import.ingest_zip_bytes(_make_zip({
        "skill-a/SKILL.md": _skill_md("skill-a"),
        "skill-a/references/doc.md": b"# doc\n",
        "nested/skill-b/SKILL.md": _skill_md("skill-b"),
        "nested/skill-b/scripts/run.sh": b"echo hi\n",
    }))

    candidates = {c.root: c for c in skill_import.discover_candidates(entries, tmp_path)}

    assert set(candidates) == {"skill-a", "nested/skill-b"}
    first = candidates["skill-a"]
    assert first.ok is True
    assert first.name == "skill-a"
    assert first.description == "A test skill"
    assert first.has_scripts is False
    assert first.file_count == 2
    assert first.conflict is False
    assert first.diagnostics == []
    second = candidates["nested/skill-b"]
    assert second.has_scripts is True
    assert second.script_files == ["scripts/run.sh"]


def test_discover_candidates_bad_candidate_diagnostics(tmp_path):
    entries = [skill_import.IngestEntry(path="broken/SKILL.md", data=b"---\nname: broken\n---\n")]

    (candidate,) = skill_import.discover_candidates(entries, tmp_path)

    assert candidate.ok is False
    assert candidate.name is None
    assert candidate.description is None
    assert [d.kind for d in candidate.diagnostics] == ["description-missing"]


def test_discover_candidates_invalid_utf8_diagnostic(tmp_path):
    entries = [skill_import.IngestEntry(path="broken/SKILL.md", data=b"\xff\xfe")]

    (candidate,) = skill_import.discover_candidates(entries, tmp_path)

    assert candidate.ok is False
    assert [d.kind for d in candidate.diagnostics] == ["invalid-utf8"]


def test_discover_candidates_marks_conflict(tmp_path):
    (tmp_path / "skill-a").mkdir()
    entries = [skill_import.IngestEntry(path="s/SKILL.md", data=_skill_md("skill-a"))]

    (candidate,) = skill_import.discover_candidates(entries, tmp_path)

    assert candidate.conflict is True


# ── stash 生命周期 ──────────────────────────────────────────────────


def test_stash_roundtrip(tmp_path):
    base = tmp_path / "stash"
    entries = [skill_import.IngestEntry(path="s/SKILL.md", data=_skill_md("s"))]

    token = skill_import_stash.stash_payload(base, entries, kind="zip")

    assert isinstance(token, str) and len(token) >= 16
    stored = skill_import_stash.load_stash_entries(base, token)
    assert stored == [("s/SKILL.md", _skill_md("s"))]
    meta = json.loads((base / token / "meta.json").read_text(encoding="utf-8"))
    assert meta["kind"] == "zip"
    assert meta["source_url"] == ""
    skill_import_stash.drop_stash(base, token)
    assert not (base / token).exists()


def test_stash_cleanup_removes_expired_keeps_fresh(tmp_path):
    base = tmp_path / "stash"
    stale = base / "old-token"
    (stale / "tree").mkdir(parents=True)
    (stale / "meta.json").write_text(
        json.dumps({"created_at": time.time() - 3600}), encoding="utf-8"
    )
    fresh = base / "fresh-token"
    (fresh / "tree").mkdir(parents=True)
    (fresh / "meta.json").write_text(
        json.dumps({"created_at": time.time()}), encoding="utf-8"
    )

    skill_import_stash.cleanup_stash(base)

    assert not stale.exists()
    assert fresh.exists()


def test_stash_load_rejects_bad_token(tmp_path):
    base = tmp_path / "stash"
    base.mkdir()
    with pytest.raises(HTTPException) as exc:
        skill_import_stash.load_stash_entries(base, "../escape")
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        skill_import_stash.load_stash_entries(base, "no-such-token")
    assert exc.value.status_code == 404


def test_stash_load_expired_404(tmp_path):
    base = tmp_path / "stash"
    token_dir = base / "expired-token"
    (token_dir / "tree").mkdir(parents=True)
    (token_dir / "meta.json").write_text(
        json.dumps({"created_at": time.time() - 3600}), encoding="utf-8"
    )

    with pytest.raises(HTTPException) as exc:
        skill_import_stash.load_stash_entries(base, "expired-token")

    assert exc.value.status_code == 404
    assert not token_dir.exists()


# ── 安装落盘 ────────────────────────────────────────────────────────


def _stashed_skill(tmp_path, name: str = "real-name", root: str = "vendor-dir"):
    stash_base = tmp_path / "stash"
    catalog_dir = tmp_path / "skills"
    catalog_dir.mkdir()
    entries = [
        skill_import.IngestEntry(path=f"{root}/SKILL.md", data=_skill_md(name)),
        skill_import.IngestEntry(path=f"{root}/references/doc.md", data=b"# doc\n"),
    ]
    token = skill_import_stash.stash_payload(stash_base, entries, kind="zip")
    return stash_base, catalog_dir, token


def test_install_from_stash_success(tmp_path):
    stash_base, catalog_dir, token = _stashed_skill(tmp_path)

    name, backup = skill_import.install_from_stash(
        stash_base, token, "vendor-dir", catalog_dir
    )

    assert name == "real-name"
    assert backup is None
    assert (catalog_dir / "real-name" / "SKILL.md").exists()
    assert (catalog_dir / "real-name" / "references" / "doc.md").exists()
    # confirm 用后即删
    assert not (stash_base / token).exists()


def test_install_from_stash_conflict_409_then_overwrite_backup(tmp_path):
    stash_base, catalog_dir, token = _stashed_skill(tmp_path)
    existing = catalog_dir / "real-name"
    existing.mkdir()
    (existing / "local.txt").write_text("custom\n", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        skill_import.install_from_stash(stash_base, token, "vendor-dir", catalog_dir)
    assert exc.value.status_code == 409
    # 409 后 stash 保留，可用 overwrite 重试
    name, backup = skill_import.install_from_stash(
        stash_base, token, "vendor-dir", catalog_dir, overwrite=True
    )

    assert name == "real-name"
    assert backup is not None
    assert backup.parent.name == ".preset-backups"
    assert (backup / "local.txt").exists()
    assert not (catalog_dir / "real-name" / "local.txt").exists()


def test_install_from_stash_invalid_candidate_422(tmp_path):
    stash_base = tmp_path / "stash"
    catalog_dir = tmp_path / "skills"
    catalog_dir.mkdir()
    entries = [skill_import.IngestEntry(path="broken/SKILL.md", data=b"---\nname: broken\n---\n")]
    token = skill_import_stash.stash_payload(stash_base, entries, kind="zip")

    with pytest.raises(HTTPException) as exc:
        skill_import.install_from_stash(stash_base, token, "broken", catalog_dir)

    assert exc.value.status_code == 422
    assert exc.value.detail["diagnostics"]


def test_install_from_stash_mkdtemp_failure_preserves_original(tmp_path, monkeypatch):
    """staging 创建先于 backup 改名：mkdtemp 失败时旧副本原样保留、无备份残留。"""
    stash_base, catalog_dir, token = _stashed_skill(tmp_path)
    existing = catalog_dir / "real-name"
    existing.mkdir()
    (existing / "SKILL.md").write_bytes(_skill_md("real-name"))
    (existing / "local.txt").write_text("custom\n", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("no space left")

    monkeypatch.setattr(skill_import.tempfile, "mkdtemp", _boom)

    with pytest.raises(OSError):
        skill_import.install_from_stash(
            stash_base, token, "vendor-dir", catalog_dir, overwrite=True
        )

    assert (existing / "local.txt").read_text(encoding="utf-8") == "custom\n"
    assert not (catalog_dir / ".preset-backups").exists()


def test_install_cleans_stale_staging_dirs(tmp_path):
    """catalog 根下陈旧的 .install-* 暂存目录在安装前被惰性清理。"""
    stash_base, catalog_dir, token = _stashed_skill(tmp_path)
    stale = catalog_dir / ".install-stale"
    stale.mkdir()
    old = time.time() - 7200
    os.utime(stale, (old, old))
    fresh = catalog_dir / ".install-fresh"
    fresh.mkdir()

    skill_import.install_from_stash(stash_base, token, "vendor-dir", catalog_dir)

    assert not stale.exists()
    assert fresh.exists()
    # 安装成功不残留暂存目录
    assert not list(catalog_dir.glob(".install-*/*"))
