from pathlib import Path
import sys
import types
from unittest.mock import MagicMock

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

    def put(self, *args, **kwargs):
        return _RouteStub()


class _Request:
    pass


class _BaseModel:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def _Field(*args, **kwargs):
    return None


class _FileLock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


fastapi_mod = types.ModuleType("fastapi")
fastapi_mod.APIRouter = _APIRouter
fastapi_mod.HTTPException = _HTTPException
fastapi_mod.Request = _Request
pydantic_mod = types.ModuleType("pydantic")
pydantic_mod.BaseModel = _BaseModel
pydantic_mod.Field = _Field
filelock_mod = types.ModuleType("filelock")
filelock_mod.FileLock = _FileLock
_real_fastapi = sys.modules.get("fastapi")
_real_pydantic = sys.modules.get("pydantic")
_real_filelock = sys.modules.get("filelock")
sys.modules.setdefault("fastapi", fastapi_mod)
sys.modules.setdefault("pydantic", pydantic_mod)
sys.modules.setdefault("filelock", filelock_mod)

from quickquip.app.web.routes import config  # noqa: E402

if _real_fastapi is not None:
    sys.modules["fastapi"] = _real_fastapi
else:
    sys.modules.pop("fastapi", None)
if _real_pydantic is not None:
    sys.modules["pydantic"] = _real_pydantic
else:
    sys.modules.pop("pydantic", None)
if _real_filelock is not None:
    sys.modules["filelock"] = _real_filelock
else:
    sys.modules.pop("filelock", None)

HTTPException = _HTTPException


def _mock_request():
    req = MagicMock()
    req.client.host = "127.0.0.1"
    return req


def _patch_config_dir(monkeypatch, tmp_path: Path) -> Path:
    base = tmp_path / "config"
    base.mkdir()
    monkeypatch.setattr(config, "_CONFIG_DIR", base)
    return base


def test_list_configs_does_not_expose_sensitive_words(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)

    result = config.list_configs()

    keys = {item["key"] for item in result["configs"]}
    filenames = {item["filename"] for item in result["configs"]}
    assert "sensitive_words" not in keys
    assert "sensitive_words.toml" not in filenames


def test_sensitive_words_config_key_is_not_readable(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as exc:
        config.get_config("sensitive_words")

    assert exc.value.status_code == 404


def test_sensitive_words_config_key_is_not_writable(monkeypatch, tmp_path):
    _patch_config_dir(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as exc:
        config.put_config(
            "sensitive_words",
            config.ConfigBody(content="[block]\nwords = [\"secret\"]\n"),
            _mock_request(),
        )

    assert exc.value.status_code == 404
    assert not (tmp_path / "config" / "sensitive_words.toml").exists()
