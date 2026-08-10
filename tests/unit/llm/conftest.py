import pytest


@pytest.fixture(autouse=True)
def _no_usage_metering(monkeypatch):
    """禁用 complete() 的 usage 记录，避免 provider 单测写真实 data/llm_usage.db。

    需测计量本身的测试（test_usage_metering）在测试体内 monkeypatch
    base._record_usage 覆盖为 spy。
    """

    async def _noop(*args, **kwargs):
        pass

    monkeypatch.setattr("quickquip.llm.provider.base._record_usage", _noop)
