"""思考档位的 scope 覆盖链：命令写 → 持久化 → 设置解析 → 请求装配 → 状态展示。

档位词表单源 config.REASONING_EFFORT_CHOICES；scope 覆盖为三态
（None = 跟随 provider 配置档）。展示面三层口径：渠道配置 / 本群或私聊
覆盖 / 实际下发结果（openai 系经 resolve_thinking，openai_responses 经
profile 词表层 reasoning_control）。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from plugins.llm_runtime import LLMService
from quickquip.llm.provider import LLMResponse
from tests.fixtures.configs import write_llm_config_bundle

_TOML = """
[runtime]
enabled = true
default_provider = "p-plain"
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
id = "p-plain"
protocol = "openai"
base_url = "https://plain.example.test/v1"
api_key_env = "PLAIN_KEY"
default_model = "gpt-test"
models = ["gpt-test"]

[[providers]]
id = "p-glm"
protocol = "openai"
base_url = "https://glm.example.test/v1"
api_key_env = "GLM_KEY"
default_model = "glm-5.3"
models = ["glm-5.3"]
reasoning_effort = "low"

[[providers]]
id = "p-glm-default"
protocol = "openai"
base_url = "https://glm2.example.test/v1"
api_key_env = "GLM2_KEY"
default_model = "glm-5.3"
models = ["glm-5.3"]

[[providers]]
id = "p-resp"
protocol = "openai_responses"
base_url = "https://resp.example.test/v1"
api_key_env = "RESP_KEY"
default_model = "gpt-5.3-codex"
models = ["gpt-5.3-codex"]
responses_profile = "codex-http-relay"

[[providers]]
id = "p-gemini-flash"
protocol = "gemini"
base_url = "https://gemini.example.test/v1beta"
api_key_env = "GEMINI_KEY"
default_model = "gemini-2.5-flash"
models = ["gemini-2.5-flash"]

[[providers]]
id = "p-kimi-claude"
protocol = "claude"
base_url = "https://kimi.example.test/anthropic"
api_key_env = "KIMI_KEY"
default_model = "k3"
models = ["k3"]
"""


def _make_service(tmp_path: Path) -> LLMService:
    bundle = write_llm_config_bundle(tmp_path, config_toml=textwrap.dedent(_TOML).strip())
    return LLMService(**bundle)


def test_resolve_effort_without_override_uses_provider_config(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    settings = service.get_chat_settings(123)
    assert settings.reasoning_effort == ""  # p-plain 未配置档位
    assert settings.reasoning_effort_override is None

    service.set_chat_model(123, "p-glm", "glm-5.3")
    settings = service.get_chat_settings(123)
    assert settings.reasoning_effort == "low"  # provider 配置档
    assert settings.reasoning_effort_override is None


def test_set_effort_override_roundtrip(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    service.set_chat_reasoning_effort(123, "high")
    settings = service.get_chat_settings(123)
    assert settings.reasoning_effort == "high"
    assert settings.reasoning_effort_override == "high"

    # 清覆盖后回落 provider 配置档（p-plain 未配置 → 空 = 模型默认档）
    service.set_chat_reasoning_effort(123, None)
    settings = service.get_chat_settings(123)
    assert settings.reasoning_effort == ""
    assert settings.reasoning_effort_override is None


def test_set_effort_rejects_unknown_tier(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    with pytest.raises(ValueError, match="未知思考档位"):
        service.set_chat_reasoning_effort(123, "extreme")
    # 非法写入不落库
    assert service.get_chat_settings(123).reasoning_effort_override is None


async def test_generate_reply_carries_scope_effort(tmp_path: Path, monkeypatch) -> None:
    captured: list = []

    class _CaptureClient:
        async def complete(self, request):
            captured.append(request)
            return LLMResponse(text="ok", model=request.model, finish_reason="stop")

    monkeypatch.setattr(
        "quickquip.llm.service.build_provider_client", lambda provider: _CaptureClient()
    )
    service = _make_service(tmp_path)
    service.set_chat_reasoning_effort(123, "high")

    result = await service.generate_reply(group_id=123, user_id=1, sender_name="t", prompt="hi")

    assert result["llm_used"] is True
    assert captured and captured[0].reasoning_effort == "high"


async def test_generate_reply_default_effort_sends_none(tmp_path: Path, monkeypatch) -> None:
    captured: list = []

    class _CaptureClient:
        async def complete(self, request):
            captured.append(request)
            return LLMResponse(text="ok", model=request.model, finish_reason="stop")

    monkeypatch.setattr(
        "quickquip.llm.service.build_provider_client", lambda provider: _CaptureClient()
    )
    service = _make_service(tmp_path)

    result = await service.generate_reply(group_id=123, user_id=1, sender_name="t", prompt="hi")

    assert result["llm_used"] is True
    assert captured and captured[0].reasoning_effort is None


def test_format_effort_status_default(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    line = service.format_effort_status(123)
    assert "渠道 未配置" in line
    assert "本群 未覆盖" in line
    assert "实际 按模型自身默认档运行" in line


def test_format_effort_status_shows_openai_clamp(tmp_path: Path) -> None:
    """三档系 GLM：medium 自动调整为 high，渠道/本群/实际三层各自可见。"""
    service = _make_service(tmp_path)
    service.set_chat_model(123, "p-glm", "glm-5.3")
    service.set_chat_reasoning_effort(123, "medium")
    line = service.format_effort_status(123)
    assert "渠道 low" in line
    assert "本群 medium" in line
    assert "实际 按 high 下发（该后端不支持 medium，已自动调整）" in line


def test_format_effort_status_responses_profile_clamp(tmp_path: Path) -> None:
    """codex-http-relay 词表止于 max：ultra 经 profile 降档层自动调整为 max。"""
    service = _make_service(tmp_path)
    service.set_chat_model(123, "p-resp", "gpt-5.3-codex")
    service.set_chat_reasoning_effort(123, "ultra")
    line = service.format_effort_status(123)
    assert "本群 ultra" in line
    assert "实际 按 max 下发（该后端不支持 ultra，已自动调整）" in line


def test_format_effort_status_unsupported_combo(tmp_path: Path) -> None:
    """非 Claude 家族挂 claude 协议：明确说明不下发、原因与模型自身默认档。"""
    service = _make_service(tmp_path)
    service.set_chat_model(123, "p-kimi-claude", "k3")
    service.set_chat_reasoning_effort(123, "high")
    line = service.format_effort_status(123)
    assert "本群 high" in line
    assert "不下发：该渠道（claude 协议）与 k3 的组合当前无法下发思考参数" in line
    assert "模型按自身默认档运行（该模型默认即最高档）" in line


def test_format_effort_status_missing_provider(tmp_path: Path) -> None:
    """渠道已删除但有覆盖：明确报渠道缺失，不伪造实际行为。"""
    service = _make_service(tmp_path)
    service.set_chat_reasoning_effort(123, "high")
    service.store.update_group_settings("123", provider_id="p-deleted")
    line = service.format_effort_status(123)
    assert "渠道 未知" in line
    assert "本群 high" in line
    assert "无法解析：渠道配置缺失" in line


def test_format_effort_status_private_scope_label(tmp_path: Path) -> None:
    """私聊 scope 标签为「私聊」。"""
    service = _make_service(tmp_path)
    line = service.format_effort_status(123, chat_type="private")
    assert "私聊 未覆盖" in line


def test_format_status_includes_effort_line(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    assert "思考档位：" in service.format_status(123)


def test_format_effort_status_hints_max_default_family(tmp_path: Path) -> None:
    """GLM/Kimi/MiniMax 系未配置档位时：生效 默认 附默认即最高档提示。"""
    service = _make_service(tmp_path)
    service.set_chat_model(123, "p-glm-default", "glm-5.3")
    line = service.format_effort_status(123)
    assert "按模型自身默认档运行（glm-5.3 的默认档即最高档）" in line

    # 非默认即最高档家族（gpt-test）不带提示
    service.set_chat_model(123, "p-plain", "gpt-test")
    line = service.format_effort_status(123)
    assert "实际 按模型自身默认档运行" in line
    assert "最高档" not in line
    assert "思考档位：" in service.format_current(123)


def test_format_effort_status_gemini_flash_clamp_reason(tmp_path: Path) -> None:
    """gemini 2.5 Flash 的 max 档受模型上限 24576 限制：文案不写 max_output_tokens。"""
    service = _make_service(tmp_path)
    service.set_chat_model(123, "p-gemini-flash", "gemini-2.5-flash")
    service.set_chat_reasoning_effort(123, "max")
    line = service.format_effort_status(123)
    assert "思考预算 24576 tokens（受模型上限限制）" in line
    assert "max_output_tokens" not in line


async def test_history_projection_receives_scope_effort(tmp_path: Path, monkeypatch) -> None:
    """历史重放投影的密文回落档取请求生效档（群覆盖优先于 provider 配置档）。"""

    class _CaptureClient:
        async def complete(self, request):
            return LLMResponse(text="ok", model=request.model, finish_reason="stop")

    monkeypatch.setattr(
        "quickquip.llm.service.build_provider_client", lambda provider: _CaptureClient()
    )
    service = _make_service(tmp_path)
    captured: dict = {}
    monkeypatch.setattr(
        service,
        "_projected_history_segments",
        lambda **kwargs: captured.update(kwargs) or {},
    )

    service.set_chat_reasoning_effort(123, "max")
    await service.generate_reply(group_id=123, user_id=1, sender_name="t", prompt="hi")
    assert captured["effort"] == "max"

    # 清覆盖后回落 provider 配置档（p-plain 未配置 → 空 = 默认档画像）
    captured.clear()
    service.set_chat_reasoning_effort(123, None)
    await service.generate_reply(group_id=123, user_id=1, sender_name="t", prompt="hi")
    assert captured["effort"] == ""
