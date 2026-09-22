"""Auto-memory judge outcome classification tests.

quick_judge_detailed 的非 ok 结果（length/empty/provider_error）按
"本轮无可抽取记忆"跳过，不再以 ERROR 堆栈刷日志；ok 但正文不可解析
单独计数并降级为 warning。
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from quickquip.llm.quick_judge import QuickJudgeResult
from quickquip.llm.service_parts.auto_memory import AutoMemoryMixin


class _FakeSnapshot:
    def name(self, user_id, fallback):
        return str(fallback)


class _FakeIdentityRepository:
    def snapshot(self, scope_key):
        return _FakeSnapshot()


class _FakeStore:
    def __init__(self) -> None:
        self.memories: list[str] = []

    def list_recent_conversation_messages(self, scope_key, limit):
        return []

    def search_memories(self, *args, **kwargs):
        return []

    def add_memory(self, scope_key, content, **kwargs):
        self.memories.append(content)

    def prune_memories(self, *args, **kwargs):
        pass


class _Host(AutoMemoryMixin):
    def __init__(self, judge: QuickJudgeResult) -> None:
        self._init_auto_memory()
        self._judge = judge
        self.config = SimpleNamespace(
            runtime=SimpleNamespace(
                auto_memory_prompt="",
                auto_memory_max_tokens=256,
                memory_max_items_per_group=50,
            )
        )
        self.store = _FakeStore()
        self._identity_repository = _FakeIdentityRepository()

    async def quick_judge_detailed(self, prompt, max_tokens=None):
        return self._judge


def _qj(text: str, outcome: str = "ok", **kwargs) -> QuickJudgeResult:
    return QuickJudgeResult(text=text, outcome=outcome, provider_id="p", model="m", **kwargs)


async def _extract(host: _Host) -> None:
    scope = "g:1001"
    host._auto_memory_turns[scope] = 9  # 下一次调用凑齐批量触发
    await host._extract_auto_memory(
        scope_key=scope,
        user_id=2002,
        sender_name="测试用户",
        user_text="这是一条足够长的用户发言内容",
        assistant_text="这是一条足够长的助手回复内容，超过二十字没有问题",
    )


@pytest.mark.asyncio
async def test_length_outcome_skips_quietly(caplog):
    """reasoning 耗尽预算（finish_reason=length、可见正文为空）按跳过处理。"""
    host = _Host(_qj("", outcome="length", finish_reason="length"))
    with caplog.at_level(logging.DEBUG):
        await _extract(host)
    assert host.store.memories == []
    assert host._auto_memory_failures == 1
    assert host._auto_memory_successes == 0
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.asyncio
async def test_empty_outcome_skips_quietly(caplog):
    host = _Host(_qj("", outcome="empty"))
    with caplog.at_level(logging.DEBUG):
        await _extract(host)
    assert host.store.memories == []
    assert host._auto_memory_failures == 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.asyncio
async def test_provider_error_warns_without_traceback(caplog):
    host = _Host(_qj("", outcome="provider_error"))
    with caplog.at_level(logging.DEBUG):
        await _extract(host)
    assert host.store.memories == []
    assert host._auto_memory_failures == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert not any(r.exc_info for r in warnings)


@pytest.mark.asyncio
async def test_unparsable_ok_text_warns_without_traceback(caplog):
    host = _Host(_qj("这不是 JSON"))
    with caplog.at_level(logging.DEBUG):
        await _extract(host)
    assert host.store.memories == []
    assert host._auto_memory_failures == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert not any(r.exc_info for r in warnings)


@pytest.mark.asyncio
async def test_ok_outcome_stores_memories():
    host = _Host(_qj('{"memories": ["小明是程序员"]}'))
    await _extract(host)
    assert host.store.memories == ["小明是程序员"]
    assert host._auto_memory_successes == 1
    assert host._auto_memory_failures == 0
