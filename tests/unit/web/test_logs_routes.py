from pathlib import Path
import sys
import types

import pytest


class _HTTPException(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _RouteStub:
    def __call__(self, fn):
        return fn


class _APIRouter:
    def get(self, *args, **kwargs):
        return _RouteStub()


class _Query:
    def __init__(self, default=None, **kwargs):
        self.default = default

    def __repr__(self):
        return repr(self.default)


class _FileResponse:
    def __init__(self, path, media_type=None, filename=None):
        self.path = Path(path)
        self.media_type = media_type
        self.filename = filename


class _StreamingResponse:
    def __init__(self, body_iterator, media_type=None, headers=None):
        self.body_iterator = body_iterator
        self.media_type = media_type
        self.headers = headers or {}


fastapi_mod = types.ModuleType("fastapi")
fastapi_mod.APIRouter = _APIRouter
fastapi_mod.HTTPException = _HTTPException
fastapi_mod.Query = _Query
responses_mod = types.ModuleType("fastapi.responses")
responses_mod.FileResponse = _FileResponse
responses_mod.StreamingResponse = _StreamingResponse
_real_fastapi = sys.modules.get("fastapi")
_real_fastapi_responses = sys.modules.get("fastapi.responses")
sys.modules.setdefault("fastapi", fastapi_mod)
sys.modules.setdefault("fastapi.responses", responses_mod)

from quickquip.app.web.routes import logs  # noqa: E402

if _real_fastapi is not None:
    sys.modules["fastapi"] = _real_fastapi
else:
    sys.modules.pop("fastapi", None)
if _real_fastapi_responses is not None:
    sys.modules["fastapi.responses"] = _real_fastapi_responses
else:
    sys.modules.pop("fastapi.responses", None)


def _patch_logs_dir(monkeypatch, tmp_path: Path) -> Path:
    base = tmp_path / "logs"
    base.mkdir()
    monkeypatch.setattr(logs, "_LOGS_DIR", base)
    return base


def test_list_logs_sorts_and_marks_current(monkeypatch, tmp_path):
    base = _patch_logs_dir(monkeypatch, tmp_path)
    (base / "quickquip_2026-05-09.log").write_text("y\n", encoding="utf-8")
    (base / "quickquip_2026-05-10.log").write_text("x\n", encoding="utf-8")
    (base / "ignore.txt").write_text("nope", encoding="utf-8")

    result = logs.list_logs()

    assert result["current_file"] == "quickquip_2026-05-10.log"
    assert [item["name"] for item in result["files"]] == ["quickquip_2026-05-10.log", "quickquip_2026-05-09.log"]
    assert result["files"][0]["is_current"] is True


def test_get_log_tail_returns_last_lines(monkeypatch, tmp_path):
    base = _patch_logs_dir(monkeypatch, tmp_path)
    path = base / "quickquip_2026-05-10.log"
    path.write_text("line1\nline2\nline3\n", encoding="utf-8")

    result = logs.get_log_tail("quickquip_2026-05-10.log", lines=2)

    assert result["lines"] == ["line2", "line3"]
    assert result["name"] == "quickquip_2026-05-10.log"


def test_get_log_tail_rejects_invalid_name(monkeypatch, tmp_path):
    _patch_logs_dir(monkeypatch, tmp_path)

    with pytest.raises(Exception) as exc:
        logs.get_log_tail("../secret.log")

    assert getattr(exc.value, "status_code", None) == 422
