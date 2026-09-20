"""ScopeGate（同 scope 串行闸门，设计 §5.2）单元测试。

回收类用例注入假时钟推进时间、以 ``tracked_scope_count`` 等可观测面
断言，不触碰私有状态，也不依赖真实时钟基址（CI 容器 uptime 可能短于
回收间隔）。
"""
from __future__ import annotations

import asyncio
import logging

from quickquip.llm.service_parts.scope_gate import ScopeGate


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def test_serializes_same_scope_and_parallelizes_distinct_scopes():
    gate = ScopeGate()
    order: list[str] = []

    async def worker(tag: str, hold: float) -> None:
        async with gate.guarded("g1" if tag in ("a1", "a2") else "g2"):
            order.append(f"enter-{tag}")
            await asyncio.sleep(hold)
            order.append(f"exit-{tag}")

    await asyncio.gather(
        worker("a1", 0.05),
        worker("a2", 0.0),
        worker("b1", 0.0),
    )

    # 同 scope 完全串行：a2 的 enter 在 a1 的 exit 之后
    assert order.index("exit-a1") < order.index("enter-a2")
    # 异 scope 不互相阻塞（b1 在 a1 持有期间即已完成）
    assert order.index("exit-b1") < order.index("exit-a1")


async def test_cancelled_waiter_leaves_no_residue():
    gate = ScopeGate()
    release = asyncio.Event()

    async def holder() -> None:
        async with gate.guarded("g"):
            await release.wait()

    async def waiter() -> None:
        async with gate.guarded("g"):
            pass

    h = asyncio.create_task(holder())
    await asyncio.sleep(0.01)
    w = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    w.cancel()
    release.set()
    await asyncio.gather(h, w, return_exceptions=True)

    async with gate.guarded("g"):
        pass  # 取消的等待者不得留下残留占用


async def test_idle_entry_reaped_after_threshold():
    clock = _FakeClock()
    gate = ScopeGate(clock=clock)

    async with gate.guarded("g"):
        pass
    assert gate.tracked_scope_count == 1

    # 推进超过「回收间隔 + 空闲保留」两个阈值后，任何一次取闸门都会
    # 顺带回收久置空闲条目。
    clock.advance(2_000.0)
    async with gate.guarded("h"):
        pass

    assert gate.tracked_scope_count == 1  # 只剩新用的 h


async def test_held_and_waiting_entries_survive_reap():
    clock = _FakeClock()
    gate = ScopeGate(clock=clock)
    release = asyncio.Event()

    async def holder() -> None:
        async with gate.guarded("g"):
            await release.wait()

    h = asyncio.create_task(holder())
    w = asyncio.create_task(holder())
    await asyncio.sleep(0.01)

    # 越过全部回收阈值并触发一次回收：在持/排队条目必须幸存
    clock.advance(2_000.0)
    async with gate.guarded("h"):
        assert gate.tracked_scope_count >= 2  # g（在持）与 h 并存

    release.set()
    await asyncio.gather(h, w)


async def test_hold_reports_waited_seconds():
    gate = ScopeGate()
    release = asyncio.Event()

    async def holder() -> None:
        async with gate.guarded("g"):
            await release.wait()

    async def waiter() -> None:
        async with gate.guarded("g") as hold:
            assert hold.waited_s > 0.01

    h = asyncio.create_task(holder())
    await asyncio.sleep(0.01)
    w = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)
    release.set()
    await asyncio.gather(h, w)

    async with gate.guarded("g") as hold:
        assert hold.waited_s < 0.01  # 无竞争时等待近零


def test_record_bypass_counts_and_logs(caplog):
    gate = ScopeGate()
    with caplog.at_level(logging.ERROR, logger="quickquip.llm.service_parts.scope_gate"):
        gate.record_bypass("1001", "scope=1001 已有未关闭 Loop loop_x")

    assert gate.bypassed_count == 1
    assert "scope-gate-alarm" in caplog.text


async def test_degraded_service_generate_reply_returns_graceful_error(monkeypatch):
    """降级单例（__new__ 构造不走 __init__）也能过闸门返回优雅错误。

    回归守卫：闸门在 config.load_error 优雅返回之前被访问，降级属性
    清单漏掉 _scope_gate 时该路径变 AttributeError（独立 CR B1）。
    """
    import quickquip.llm.service as service_module

    def _boom(self, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(service_module, "_llm_service", None)
    monkeypatch.setattr(service_module, "_init_attempted", False)
    monkeypatch.setattr(service_module.LLMService, "__init__", _boom)

    svc = service_module.get_llm_service()
    assert svc._init_error == "boom"

    result = await svc.generate_reply(
        group_id=1001, user_id=2002, sender_name="甲", prompt="测试"
    )
    assert "LLM 配置不可用" in result["reply"]
