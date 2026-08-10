import asyncio

from quickquip.llm.usage import _USAGE_SCOPE, set_usage_scope, usage_scope


def test_usage_scope_contextmanager_sets_and_resets():
    assert _USAGE_SCOPE.get() is None
    with usage_scope("chat", group_id="g1", persona_id="p1"):
        scope = _USAGE_SCOPE.get()
        assert scope is not None
        assert scope.feature == "chat"
        assert scope.group_id == "g1"
        assert scope.persona_id == "p1"
    assert _USAGE_SCOPE.get() is None


def test_usage_scope_nested_inner_resets_to_outer():
    with usage_scope("chat", group_id="g"):
        assert _USAGE_SCOPE.get().feature == "chat"
        with usage_scope("vision"):
            assert _USAGE_SCOPE.get().feature == "vision"
            assert _USAGE_SCOPE.get().group_id is None
        assert _USAGE_SCOPE.get().feature == "chat"
        assert _USAGE_SCOPE.get().group_id == "g"
    assert _USAGE_SCOPE.get() is None


def test_set_usage_scope_does_not_reset():
    """set_usage_scope 不 reset（用于 create_task 隔离子任务）。"""
    try:
        assert _USAGE_SCOPE.get() is None
        set_usage_scope("health")
        assert _USAGE_SCOPE.get().feature == "health"
    finally:
        _USAGE_SCOPE.set(None)


async def test_usage_scope_propagates_along_await_chain():
    """ContextVar 在同一协程的 await 链上传播（接线有效性的前提）。"""
    seen: list[str] = []

    async def inner():
        scope = _USAGE_SCOPE.get()
        seen.append(scope.feature if scope else None)

    with usage_scope("chat", group_id="g"):
        await inner()
        await asyncio.sleep(0)  # 让出一次事件循环
        await inner()
    assert seen == ["chat", "chat"]
