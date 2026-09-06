from __future__ import annotations

import random
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tests.fixtures.configs import llm_config_paths, llm_service  # noqa: F401 (re-exported)


FROZEN_NOW = datetime(2026, 3, 16, 9, 19, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture
def frozen_now() -> datetime:
    return FROZEN_NOW


@pytest.fixture
def rng() -> random.Random:
    return random.Random(42)


@pytest.fixture
def patch_provider_builder(monkeypatch):
    import quickquip.llm.service as llm_runtime_module

    def _patch(builder):
        monkeypatch.setattr(llm_runtime_module, "build_provider_client", builder)

    return _patch


@pytest.fixture(scope="session", autouse=True)
def _freeze_reply_probability():
    """既有规则回归测试假定命中必回的确定性。

    CI 环境把 chat_rules.toml.example 复制为部署配置，而 example 自带
    触发概率推荐默认，会让这些测试随掷骰随机失败；概率机制自身的行为
    由 test_reply_probability.py 的合成规则覆盖，这里清空加载态里的
    概率与方差字段，为整个测试会话提供确定性基线。
    """
    from quickquip.chat import config as chat_config

    for rule in chat_config.TEXT_REPLY_RULES + chat_config.CONTEXT_REPLY_RULES:
        rule.pop("probability", None)
    for entry in chat_config.RATE_LIMIT_RULES.values():
        entry.pop("probability", None)
        entry.pop("suppress_after_hit", None)
        entry.pop("pity_step", None)
    yield
