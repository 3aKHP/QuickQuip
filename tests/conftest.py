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
