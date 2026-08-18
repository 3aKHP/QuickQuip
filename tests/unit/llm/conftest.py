import pytest

from quickquip.llm import usage as usage_module
from quickquip.llm.usage_store import LLMUsageStore


@pytest.fixture(autouse=True)
def _tmp_usage_store(monkeypatch, tmp_path):
    """把 usage 单例指向临时库，provider 单测经 complete() 触发的计量写库
    不落真实 data/llm_usage.db；需测计量本身的测试自行覆盖为 spy/独立 store。"""
    monkeypatch.setattr(
        "quickquip.llm.usage_store.usage_store", LLMUsageStore(tmp_path / "usage.db")
    )
    yield
    # 清掉本测试事件循环里残留的在途任务强引用：cancel 在已关闭的循环上会抛
    # RuntimeError，clear 让其随循环销毁，也避免后续测试 drain 到跨循环任务。
    usage_module._USAGE_TASKS.clear()
