import pytest

from quickquip.llm.usage_store import LLMUsageStore


@pytest.fixture(autouse=True)
def _tmp_usage_store(monkeypatch, tmp_path):
    """把 usage 单例指向临时库，provider 单测经 complete() 触发的计量写库
    不落真实 data/llm_usage.db；需测计量本身的测试自行覆盖为 spy/独立 store。"""
    monkeypatch.setattr(
        "quickquip.llm.usage_store.usage_store", LLMUsageStore(tmp_path / "usage.db")
    )
