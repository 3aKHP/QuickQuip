import sys
import types


class _RouteStub:
    def __call__(self, fn):
        return fn


class _APIRouter:
    def get(self, *args, **kwargs):
        return _RouteStub()


fastapi_mod = types.ModuleType("fastapi")
fastapi_mod.APIRouter = _APIRouter
_real_fastapi = sys.modules.get("fastapi")
sys.modules.setdefault("fastapi", fastapi_mod)

from quickquip.app.web.routes import sensitive_filter  # noqa: E402

if _real_fastapi is not None:
    sys.modules["fastapi"] = _real_fastapi
else:
    sys.modules.pop("fastapi", None)


def test_sensitive_filter_status_does_not_expose_path(monkeypatch, tmp_path):
    path = tmp_path / "sensitive_words.toml"
    path.write_text(
        """
[block]
words = ["secret"]

[soft]
words = ["watch"]
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(sensitive_filter, "CONFIG_SENSITIVE_WORDS_TOML", path)

    result = sensitive_filter.get_sensitive_filter_status()

    assert result["loaded"] is True
    assert result["config_exists"] is True
    assert result["stats"] == {"total": 2, "block": 1, "soft": 1}
    assert "config_path" not in result
