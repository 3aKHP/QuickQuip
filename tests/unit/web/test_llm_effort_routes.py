"""llm-effort 路由：llm.toml provider 级思考档位的结构化读取与行级手术。"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException

from pydantic import ValidationError  # noqa: E402

from quickquip.app.web.routes import llm_effort as routes  # noqa: E402

_SAMPLE_TOML = """\
[runtime]
enabled = true
default_provider = "alpha"

[[providers]]
# 主 provider 注释
id = "alpha"  # 行尾注释
protocol = "openai"
base_url = "https://a.example/v1"
api_key_env = "ALPHA_KEY"
default_model = "alpha-1"
models = ["alpha-1"]

[[providers]]
id = 'beta'
protocol = "openai"
base_url = "https://b.example/v1"
api_key_env = "BETA_KEY"
default_model = "beta-1"
models = ["beta-1"]
reasoning_effort = "low"  # 既有档位注释

[pricing.models."alpha-1"]
input_per_mtok = 0.14
"""


def _patch_audit_noop(monkeypatch):
    monkeypatch.setattr(routes.audit_logger, "log", lambda *a, **k: None)


def _write_sample(monkeypatch, tmp_path, content: str = _SAMPLE_TOML):
    path = tmp_path / "config" / "llm.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(routes, "_LLM_TOML", path)
    _patch_audit_noop(monkeypatch)
    return path


def _put(provider_id: str, effort: str):
    return routes.put_llm_effort(provider_id, routes.EffortBody(effort=effort), object())


def test_get_llm_effort_projects_providers(monkeypatch, tmp_path):
    """GET 解析 llm.toml：各 provider 投影 id/default_model/reasoning_effort，缺省为 ""。"""
    _write_sample(monkeypatch, tmp_path)

    payload = routes.get_llm_effort()
    assert payload == {
        "providers": [
            {"id": "alpha", "default_model": "alpha-1", "reasoning_effort": ""},
            {"id": "beta", "default_model": "beta-1", "reasoning_effort": "low"},
        ]
    }


def test_get_llm_effort_missing_file_404(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "_LLM_TOML", tmp_path / "config" / "llm.toml")

    with pytest.raises(HTTPException) as exc:
        routes.get_llm_effort()
    assert exc.value.status_code == 404


def test_put_inserts_effort_after_id_line(monkeypatch, tmp_path):
    """插入路径：无既有档位行时在 id 行后插入，注释与其余块原样保留。"""
    path = _write_sample(monkeypatch, tmp_path)

    result = _put("alpha", "high")
    assert result == {"ok": True, "effect": "manual_reload"}

    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")
    id_line = lines.index('id = "alpha"  # 行尾注释')
    assert lines[id_line + 1] == 'reasoning_effort = "high"'
    # 注释与其余块原样保留
    assert "# 主 provider 注释" in content
    assert 'reasoning_effort = "low"  # 既有档位注释' in content
    assert "[pricing.models.\"alpha-1\"]" in content
    efforts = {p["id"]: p["reasoning_effort"] for p in routes.get_llm_effort()["providers"]}
    assert efforts == {"alpha": "high", "beta": "low"}


def test_put_replaces_existing_effort_line(monkeypatch, tmp_path):
    """替换路径：既有档位行原位置改写，行尾注释保留。"""
    path = _write_sample(monkeypatch, tmp_path)

    result = _put("beta", "max")
    assert result["ok"] is True

    content = path.read_text(encoding="utf-8")
    assert 'reasoning_effort = "max"  # 既有档位注释' in content
    assert 'reasoning_effort = "low"' not in content
    assert content.count("reasoning_effort") == 1
    efforts = {p["id"]: p["reasoning_effort"] for p in routes.get_llm_effort()["providers"]}
    assert efforts == {"alpha": "", "beta": "max"}


def test_put_deletes_effort_line_on_empty(monkeypatch, tmp_path):
    """删除路径：空串删除既有档位行（回模型默认档）。"""
    path = _write_sample(monkeypatch, tmp_path)

    result = _put("beta", "")
    assert result["ok"] is True

    content = path.read_text(encoding="utf-8")
    assert "reasoning_effort" not in content
    assert "id = 'beta'" in content
    efforts = {p["id"]: p["reasoning_effort"] for p in routes.get_llm_effort()["providers"]}
    assert efforts == {"alpha": "", "beta": ""}


def test_put_rejects_invalid_effort(monkeypatch, tmp_path):
    """非法档位在请求模型层拒绝（HTTP 层即 422），文件不动。"""
    path = _write_sample(monkeypatch, tmp_path)
    original = path.read_text(encoding="utf-8")

    for bogus in ("turbo", "HIGH", " "):
        with pytest.raises(ValidationError):
            routes.EffortBody(effort=bogus)
    assert path.read_text(encoding="utf-8") == original


def test_put_unknown_provider_404(monkeypatch, tmp_path):
    """目标 provider 不存在：404 且文件不动。"""
    path = _write_sample(monkeypatch, tmp_path)
    original = path.read_text(encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        _put("gamma", "high")
    assert exc.value.status_code == 404
    assert path.read_text(encoding="utf-8") == original


def test_put_multiline_string_block_400(monkeypatch, tmp_path):
    """目标块含多行字符串：fail-closed 400，文件不动。"""
    content = _SAMPLE_TOML.replace(
        'models = ["alpha-1"]',
        'models = ["alpha-1"]\nstyle_overrides = """\n多行风格段\n"""',
        1,
    )
    path = _write_sample(monkeypatch, tmp_path, content)
    original = path.read_text(encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        _put("alpha", "high")
    assert exc.value.status_code == 400
    assert "多行字符串" in exc.value.detail
    assert path.read_text(encoding="utf-8") == original


def test_verify_edit_rejects_semantic_drift():
    """手术后语义校验：目标档位与意图不符或其余 provider 档位漂移 → 500。"""
    before = [
        {"id": "alpha", "default_model": "a", "reasoning_effort": ""},
        {"id": "beta", "default_model": "b", "reasoning_effort": "low"},
    ]
    # 目标档位与意图不符
    drifted_target = [dict(before[0], reasoning_effort="max"), before[1]]
    with pytest.raises(HTTPException) as exc:
        routes._verify_edit(before, drifted_target, "alpha", "high")
    assert exc.value.status_code == 500
    # 其余 provider 档位漂移
    drifted_other = [before[0], dict(before[1], reasoning_effort="max")]
    with pytest.raises(HTTPException) as exc:
        routes._verify_edit(before, drifted_other, "alpha", "high")
    assert exc.value.status_code == 500
    # provider 序列变化
    with pytest.raises(HTTPException) as exc:
        routes._verify_edit(before, before[:1], "alpha", "high")
    assert exc.value.status_code == 500
    # 正常结果通过
    ok_after = [dict(before[0], reasoning_effort="high"), before[1]]
    routes._verify_edit(before, ok_after, "alpha", "high")
