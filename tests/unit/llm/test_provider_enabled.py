"""钉住 provider enabled 开关的语义。

enabled = false = 暂时禁用：provider 仍留在配置里（区别于坏 provider 的剪除语义），
但不进入任何群聊可达入口——列表不展示、/llm use 拒绝、回复主链拒绝；
显式单查（/llm models <id>）仍可见，但带"已禁用"标注。
探活过滤见 test_provider_health.py，cascade 跳过见 test_briefing.py。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from plugins.llm_runtime import LLMService
from quickquip.llm.config import load_llm_config
from tests.fixtures.configs import write_llm_config_bundle

_TOML = """
[runtime]
enabled = true
default_provider = "p-on"
default_persona = "default"

[triggers]
default_prefix = "/ai"

[tools]
enabled = []

[[personas]]
id = "default"
display_name = "默认"
system_prompt = "hi"

[[providers]]
id = "p-on"
protocol = "openai"
base_url = "https://on.example.test/v1"
api_key_env = "ON_KEY"
default_model = "m1"
models = ["m1"]

[[providers]]
id = "p-off"
protocol = "openai"
base_url = "https://off.example.test/v1"
api_key_env = "OFF_KEY"
default_model = "m1"
models = ["m1"]
enabled = false
"""


def _load(tmp_path: Path):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(textwrap.dedent(_TOML).strip(), encoding="utf-8")
    return load_llm_config(config_path)


def _make_service(tmp_path: Path) -> LLMService:
    bundle = write_llm_config_bundle(tmp_path, config_toml=textwrap.dedent(_TOML).strip())
    return LLMService(**bundle)


def test_enabled_parsed_and_defaults_to_true(tmp_path: Path):
    cfg = _load(tmp_path)
    assert cfg.providers["p-on"].enabled is True
    assert cfg.providers["p-off"].enabled is False


def test_disabled_provider_stays_in_config(tmp_path: Path):
    """disabled ≠ 剪除：仍留在 providers dict，不产生 load_error。"""
    cfg = _load(tmp_path)
    assert "p-off" in cfg.providers
    assert cfg.load_error is None


def test_disabled_hidden_from_provider_and_model_lists(tmp_path: Path):
    service = _make_service(tmp_path)
    visible_ids = [p.id for p in service.list_providers()]
    assert "p-on" in visible_ids
    assert "p-off" not in visible_ids
    assert "p-off" not in service.format_providers()
    assert "[p-off]" not in service.format_models()
    # 显式单查仍可见，但带已禁用标注
    single = service.format_models("p-off")
    assert "已禁用" in single
    assert "m1" in single


def test_set_chat_model_rejects_disabled(tmp_path: Path):
    service = _make_service(tmp_path)
    with pytest.raises(ValueError, match="已禁用"):
        service.set_chat_model(123, "p-off", "m1")
    assert service.set_chat_model(123, "p-on", "m1") == "m1"


@pytest.mark.asyncio
async def test_generate_reply_rejects_disabled_provider(tmp_path: Path, monkeypatch):
    """群设置停留在被禁 provider 时：主链拒绝、不构造 client、不计费。"""
    service = _make_service(tmp_path)
    service.store.update_group_settings(123, provider_id="p-off", model="m1")

    built: list[str] = []

    class _BoomClient:
        async def complete(self, request):
            raise AssertionError("disabled provider 不应被调用")

    def _builder(provider):
        built.append(provider.id)
        return _BoomClient()

    monkeypatch.setattr("quickquip.llm.service.build_provider_client", _builder)

    result = await service.generate_reply(
        group_id=123, user_id=1, sender_name="tester", prompt="hi"
    )

    assert "已禁用" in str(result.get("reply"))
    assert result.get("llm_used") is False
    assert built == []


@pytest.mark.asyncio
async def test_quick_judge_falls_back_past_disabled_provider(tmp_path: Path):
    """quick_judge 选择链把 disabled 视为不可用：default 被禁时降级到下一个 enabled。"""
    from quickquip.llm.provider import LLMResponse
    from quickquip.llm.quick_judge import run_quick_judge_detailed

    cfg = _load(tmp_path)
    cfg.runtime.default_provider = "p-off"  # default 指向被禁 provider

    built: list[str] = []

    def _builder(provider):
        built.append(provider.id)
        return _StubJudgeClient(LLMResponse(text='{"trigger": false}', model="m1", finish_reason="stop"))

    result = await run_quick_judge_detailed(cfg, "判定一下", client_builder=_builder)

    assert built == ["p-on"]
    assert result.provider_id == "p-on"


class _StubJudgeClient:
    def __init__(self, response) -> None:
        self._response = response

    async def complete(self, request):
        return self._response
