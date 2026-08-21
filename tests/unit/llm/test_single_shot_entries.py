"""Characterization tests for the three single-shot generation entries in
``LLMService`` (v1.12.1 T1): ``generate_defectify_reply``,
``generate_turmfluch_reply`` and ``generate_card_le_nearest``.

这些测试钉住当前真实行为，包括不对称之处：
- defectify / turmfluch 的早退路径（空输入 / 敏感输入 / load_error / provider 缺失）
  只返回 4 键（reply / rate_limit_key / rule_name / llm_used），
  到达 provider 调用后的路径才补 provider_id / model 成 6 键。
- card_le_nearest 成功时只返回 4 键（reply / llm_used / provider_id / model），
  所有降级路径返回 None 而非降级 dict。

敏感词一律用合成词表（make_sensitive_filter），不依赖真实
``config/sensitive_words.toml``（该文件只存在于部署机）。
"""
from __future__ import annotations

import pytest

from plugins.llm_provider import LLMProviderError, LLMResponse
from quickquip.common.sensitive_filter import (
    DEFAULT_BLOCK_REPLY,
    DEFAULT_OUTPUT_FALLBACK,
    SensitiveFilter,
)
from tests.fixtures.provider_stubs import (
    StubBehaviorProviderClient,
    StubProviderClient,
)
from tests.fixtures.sensitive_filter import make_sensitive_filter

_CHAT = {"chat_id": 1001, "chat_type": "group"}
_DEFECTIFY_CALLER = {"user_id": "2002", "sender_name": "镜子"}

# 成功路径（含 provider 异常与空响应）的完整 6 键契约
_FULL_KEYS = {"reply", "rate_limit_key", "rule_name", "llm_used", "provider_id", "model"}
# 早退路径只有 4 键
_EARLY_KEYS = {"reply", "rate_limit_key", "rule_name", "llm_used"}


@pytest.fixture(autouse=True)
def _empty_sensitive_filter(monkeypatch):
    """默认钉死为合成空过滤器：真实词表只存在于部署机，测试不得依赖它。"""
    monkeypatch.setattr(
        "quickquip.llm.service._get_sensitive_filter", SensitiveFilter.empty
    )


def _block_filter(monkeypatch, tmp_path, word: str) -> None:
    sensitive = make_sensitive_filter(tmp_path, "block", word=word)
    monkeypatch.setattr(
        "quickquip.llm.service._get_sensitive_filter", lambda: sensitive
    )


# ---------------------------------------------------------------------------
# generate_defectify_reply
# ---------------------------------------------------------------------------


async def test_defectify_empty_input_returns_usage(llm_service):
    result = await llm_service.generate_defectify_reply(
        **_CHAT, **_DEFECTIFY_CALLER, prompt="   "
    )
    assert set(result) == _EARLY_KEYS
    assert result["reply"].startswith("用法：/defectify")
    assert result["rate_limit_key"] == "llm_chat"
    assert result["rule_name"] == "llm_defectify"
    assert result["llm_used"] is False


async def test_defectify_sensitive_input_blocked(llm_service, monkeypatch, tmp_path, patch_provider_builder):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)
    _block_filter(monkeypatch, tmp_path, "合成阻断词")

    result = await llm_service.generate_defectify_reply(
        **_CHAT, **_DEFECTIFY_CALLER, prompt="这句话里有合成阻断词"
    )
    assert set(result) == _EARLY_KEYS
    assert result["reply"] == DEFAULT_BLOCK_REPLY
    assert result["llm_used"] is False
    assert stub.last_request is None  # 拦截在 provider 调用之前


async def test_defectify_load_error_short_circuits(llm_service, monkeypatch):
    monkeypatch.setattr(llm_service.config, "load_error", "TOML 语法错误：boom")

    result = await llm_service.generate_defectify_reply(
        **_CHAT, **_DEFECTIFY_CALLER, prompt="测试内容"
    )
    assert set(result) == _EARLY_KEYS
    assert result["reply"] == "LLM 配置不可用：TOML 语法错误：boom"
    assert result["llm_used"] is False


async def test_defectify_missing_provider(llm_service):
    # 绕过 set_chat_model 的存在性校验，直接写入一个未知 provider override
    llm_service._update_chat_settings(1001, "group", provider_id="missing-provider")

    result = await llm_service.generate_defectify_reply(
        **_CHAT, **_DEFECTIFY_CALLER, prompt="测试内容"
    )
    assert set(result) == _EARLY_KEYS
    assert result["reply"] == "当前 provider 不存在：missing-provider"
    assert result["llm_used"] is False


async def test_defectify_success_six_key_contract(llm_service, patch_provider_builder):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_defectify_reply(
        **_CHAT, **_DEFECTIFY_CALLER, prompt="小蓝熊的启动速度"
    )
    assert set(result) == _FULL_KEYS
    assert result["reply"].startswith("stub::gpt-test::")
    assert "小蓝熊的启动速度" in result["reply"]
    assert result["rate_limit_key"] == "llm_chat"
    assert result["rule_name"] == "llm_defectify"
    assert result["llm_used"] is True
    assert result["provider_id"] == "openai-main"
    assert result["model"] == "gpt-test"

    request = stub.last_request
    assert request.temperature == 0.9
    assert request.tools == []
    assert request.allow_tool_calls is False
    assert request.tool_choice == "none"


async def test_defectify_provider_error_still_marks_llm_used(llm_service, patch_provider_builder):
    stub = StubBehaviorProviderClient(LLMProviderError("provider down"))
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_defectify_reply(
        **_CHAT, **_DEFECTIFY_CALLER, prompt="测试内容"
    )
    assert set(result) == _FULL_KEYS
    assert result["reply"] == "LLM 调用失败：provider down"
    assert result["llm_used"] is True
    assert result["provider_id"] == "openai-main"
    assert result["model"] == "gpt-test"


async def test_defectify_unexpected_exception(llm_service, patch_provider_builder):
    stub = StubBehaviorProviderClient(RuntimeError("weird"))
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_defectify_reply(
        **_CHAT, **_DEFECTIFY_CALLER, prompt="测试内容"
    )
    assert set(result) == _FULL_KEYS
    assert result["reply"] == "LLM 调用异常：weird"
    assert result["llm_used"] is True


async def test_defectify_empty_response_text(llm_service, patch_provider_builder):
    stub = StubBehaviorProviderClient(LLMResponse(text="  ", model="gpt-test"))
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_defectify_reply(
        **_CHAT, **_DEFECTIFY_CALLER, prompt="测试内容"
    )
    assert set(result) == _FULL_KEYS
    assert result["reply"] == "模型没有返回可显示的文本。"
    assert result["llm_used"] is True


async def test_defectify_output_scan_blocked_falls_back(llm_service, monkeypatch, tmp_path, patch_provider_builder):
    stub = StubBehaviorProviderClient(LLMResponse(text="这回复带合成输出词", model="gpt-test"))
    patch_provider_builder(lambda provider: stub)
    _block_filter(monkeypatch, tmp_path, "合成输出词")

    result = await llm_service.generate_defectify_reply(
        **_CHAT, **_DEFECTIFY_CALLER, prompt="干净的输入"
    )
    assert set(result) == _FULL_KEYS
    assert result["reply"] == DEFAULT_OUTPUT_FALLBACK
    assert result["llm_used"] is True


# ---------------------------------------------------------------------------
# generate_turmfluch_reply
# ---------------------------------------------------------------------------


async def test_turmfluch_empty_input_returns_usage(llm_service):
    result = await llm_service.generate_turmfluch_reply(**_CHAT, prompt="")
    assert set(result) == _EARLY_KEYS
    assert result["reply"].startswith("用法：/turmfluch")
    assert result["rate_limit_key"] == "sts_turmfluch"
    assert result["rule_name"] == "sts_turmfluch"
    assert result["llm_used"] is False


async def test_turmfluch_sensitive_input_blocked(llm_service, monkeypatch, tmp_path, patch_provider_builder):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)
    _block_filter(monkeypatch, tmp_path, "合成阻断词")

    result = await llm_service.generate_turmfluch_reply(
        **_CHAT, prompt="这句话里有合成阻断词"
    )
    assert set(result) == _EARLY_KEYS
    assert result["reply"] == DEFAULT_BLOCK_REPLY
    assert result["llm_used"] is False
    assert stub.last_request is None


async def test_turmfluch_load_error_short_circuits(llm_service, monkeypatch):
    monkeypatch.setattr(llm_service.config, "load_error", "boom")

    result = await llm_service.generate_turmfluch_reply(**_CHAT, prompt="今天好倒霉")
    assert set(result) == _EARLY_KEYS
    assert result["reply"] == "LLM 配置不可用：boom"
    assert result["llm_used"] is False


async def test_turmfluch_missing_provider(llm_service):
    llm_service._update_chat_settings(1001, "group", provider_id="missing-provider")

    result = await llm_service.generate_turmfluch_reply(**_CHAT, prompt="今天好倒霉")
    assert set(result) == _EARLY_KEYS
    assert result["reply"] == "当前 provider 不存在：missing-provider"
    assert result["llm_used"] is False


async def test_turmfluch_success_six_key_contract(llm_service, patch_provider_builder):
    stub = StubBehaviorProviderClient(LLMResponse(text="疑虑了", model="gpt-test"))
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_turmfluch_reply(**_CHAT, prompt="今天好倒霉")
    assert set(result) == _FULL_KEYS
    assert result["reply"] == "疑虑了"
    assert result["rate_limit_key"] == "sts_turmfluch"
    assert result["rule_name"] == "sts_turmfluch"
    assert result["llm_used"] is True
    assert result["provider_id"] == "openai-main"
    assert result["model"] == "gpt-test"

    request = stub.requests[0]
    assert request.temperature == 0.7
    assert request.tool_choice == "none"
    assert "今天好倒霉" in request.messages[-1].content


async def test_turmfluch_invalid_name_from_model(llm_service, patch_provider_builder):
    stub = StubBehaviorProviderClient(LLMResponse(text="乱七八糟", model="gpt-test"))
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_turmfluch_reply(**_CHAT, prompt="今天好倒霉")
    assert set(result) == _FULL_KEYS
    assert result["reply"] == "模型没有返回合法的卡牌/遗物名。"
    assert result["llm_used"] is True


async def test_turmfluch_provider_error_still_marks_llm_used(llm_service, patch_provider_builder):
    stub = StubBehaviorProviderClient(LLMProviderError("provider down"))
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_turmfluch_reply(**_CHAT, prompt="今天好倒霉")
    assert set(result) == _FULL_KEYS
    assert result["reply"] == "LLM 调用失败：provider down"
    assert result["llm_used"] is True
    assert result["provider_id"] == "openai-main"
    assert result["model"] == "gpt-test"


async def test_turmfluch_unexpected_exception(llm_service, patch_provider_builder):
    stub = StubBehaviorProviderClient(RuntimeError("weird"))
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_turmfluch_reply(**_CHAT, prompt="今天好倒霉")
    assert set(result) == _FULL_KEYS
    assert result["reply"] == "LLM 调用异常：weird"
    assert result["llm_used"] is True


async def test_turmfluch_output_scan_blocked_falls_back(llm_service, monkeypatch, tmp_path, patch_provider_builder):
    stub = StubBehaviorProviderClient(LLMResponse(text="疑虑了", model="gpt-test"))
    patch_provider_builder(lambda provider: stub)
    _block_filter(monkeypatch, tmp_path, "疑虑")  # 词表名本身被合成过滤器拦下

    result = await llm_service.generate_turmfluch_reply(**_CHAT, prompt="今天好倒霉")
    assert set(result) == _FULL_KEYS
    assert result["reply"] == DEFAULT_OUTPUT_FALLBACK
    assert result["llm_used"] is True


# ---------------------------------------------------------------------------
# generate_card_le_nearest
# ---------------------------------------------------------------------------


async def test_card_le_nearest_success_returns_four_keys(llm_service, patch_provider_builder):
    stub = StubBehaviorProviderClient(LLMResponse(text="疑虑了", model="gpt-test"))
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_card_le_nearest(captured="破防", **_CHAT)
    # 钉住：成功 dict 没有 rate_limit_key / rule_name，与命令路径不对称
    assert result == {
        "reply": "疑虑了",
        "llm_used": True,
        "provider_id": "openai-main",
        "model": "gpt-test",
    }

    request = stub.requests[0]
    assert request.temperature == 0.5
    assert request.tool_choice == "none"
    assert "破防" in request.messages[-1].content


async def test_card_le_nearest_uses_quick_judge_model_override(llm_service, monkeypatch, patch_provider_builder):
    monkeypatch.setattr(llm_service.config.quick_judge, "model", "gpt-alt")
    stub = StubBehaviorProviderClient(LLMResponse(text="狂宴了", model="gpt-alt"))
    patch_provider_builder(lambda provider: stub)

    result = await llm_service.generate_card_le_nearest(captured="吃席", **_CHAT)
    assert result["reply"] == "狂宴了"
    assert result["model"] == "gpt-alt"
    assert stub.requests[0].model == "gpt-alt"


async def test_card_le_nearest_load_error_returns_none(llm_service, monkeypatch):
    monkeypatch.setattr(llm_service.config, "load_error", "boom")
    assert await llm_service.generate_card_le_nearest(captured="破防", **_CHAT) is None


async def test_card_le_nearest_no_provider_returns_none(llm_service):
    llm_service.config.providers.clear()
    assert await llm_service.generate_card_le_nearest(captured="破防", **_CHAT) is None


async def test_card_le_nearest_sensitive_input_returns_none(llm_service, monkeypatch, tmp_path, patch_provider_builder):
    stub = StubBehaviorProviderClient(LLMResponse(text="疑虑了", model="gpt-test"))
    patch_provider_builder(lambda provider: stub)
    _block_filter(monkeypatch, tmp_path, "合成阻断词")

    result = await llm_service.generate_card_le_nearest(captured="合成阻断词", **_CHAT)
    assert result is None
    assert stub.requests == []  # 拦截在 provider 调用之前


async def test_card_le_nearest_provider_error_returns_none(llm_service, patch_provider_builder):
    stub = StubBehaviorProviderClient(RuntimeError("boom"))
    patch_provider_builder(lambda provider: stub)
    assert await llm_service.generate_card_le_nearest(captured="破防", **_CHAT) is None


async def test_card_le_nearest_invalid_name_returns_none(llm_service, patch_provider_builder):
    stub = StubBehaviorProviderClient(LLMResponse(text="不存在的名字了", model="gpt-test"))
    patch_provider_builder(lambda provider: stub)
    assert await llm_service.generate_card_le_nearest(captured="破防", **_CHAT) is None


async def test_card_le_nearest_output_scan_blocked_returns_none(llm_service, monkeypatch, tmp_path, patch_provider_builder):
    stub = StubBehaviorProviderClient(LLMResponse(text="疑虑了", model="gpt-test"))
    patch_provider_builder(lambda provider: stub)
    _block_filter(monkeypatch, tmp_path, "疑虑")

    assert await llm_service.generate_card_le_nearest(captured="破防", **_CHAT) is None
