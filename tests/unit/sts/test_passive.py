"""「xxx了」被动匹配器 match_card_le 的单元测试（用假 LLM service）。"""

from __future__ import annotations

import pytest

from quickquip.sts.formulas.card_le import passive


class FakeLLM:
    def __init__(self, reply: str | None = "疑虑了"):
        self.reply = reply
        self.calls = 0

    async def generate_card_le_nearest(self, *, captured, chat_id, chat_type):
        self.calls += 1
        if self.reply is None:
            return None
        return {"reply": self.reply, "llm_used": True, "provider_id": "p", "model": "m"}


@pytest.fixture(autouse=True)
def _clear_cache():
    passive._NEAREST_CACHE.clear()
    yield
    passive._NEAREST_CACHE.clear()


async def test_silent_on_real_card_name():
    svc = FakeLLM()
    # captured 是真卡名 → 静默，不调用 LLM
    assert await passive.match_card_le("疑虑了", llm_service=svc, group_id=1) is None
    assert svc.calls == 0


async def test_non_card_triggers_llm_and_replies():
    svc = FakeLLM(reply="疑虑了")
    result = await passive.match_card_le("破防了", llm_service=svc, group_id=1)
    assert result is not None
    assert result["reply"] == "疑虑了"
    assert result["rule_name"] == "sts_card_le"
    assert "破防" in result["trigger_reason"]
    assert svc.calls == 1


async def test_cache_avoids_repeat_llm_call():
    svc = FakeLLM(reply="疑虑了")
    await passive.match_card_le("破防了", llm_service=svc, group_id=1)
    await passive.match_card_le("破防了", llm_service=svc, group_id=2)
    assert svc.calls == 1  # 第二次走缓存


async def test_regex_miss_returns_none_without_llm():
    svc = FakeLLM()
    assert await passive.match_card_le("我吃完饭了，好饱", llm_service=svc, group_id=1) is None  # 了不在句末
    assert await passive.match_card_le("睡了", llm_service=svc, group_id=1) is None  # 仅 1 字
    assert svc.calls == 0


async def test_llm_no_valid_name_propagates_none():
    svc = FakeLLM(reply=None)
    assert await passive.match_card_le("破防了", llm_service=svc, group_id=1) is None
