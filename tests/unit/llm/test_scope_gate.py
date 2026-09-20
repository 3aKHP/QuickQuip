"""ScopeGate（同 scope 串行闸门，设计 §5.2）单元测试。"""
from __future__ import annotations

import asyncio

from quickquip.llm.service_parts.scope_gate import ScopeGate


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


async def test_cancelled_waiter_releases_and_next_proceeds():
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


async def test_held_and_waiting_entries_survive_reap():
    gate = ScopeGate()
    release = asyncio.Event()

    async def holder() -> None:
        async with gate.guarded("g"):
            await release.wait()

    h = asyncio.create_task(holder())
    w = asyncio.create_task(holder())
    await asyncio.sleep(0.01)

    # 强制越过回收间隔与空闲阈值：在持/排队条目绝不能被回收
    gate._last_reap = 0.0
    entry = gate._entries["g"]
    entry.released_at = -1e9
    gate._reap(1e9)

    assert "g" in gate._entries

    release.set()
    await asyncio.gather(h, w)


def test_idle_entry_reaped_after_threshold():
    import time as _time

    from quickquip.llm.service_parts.scope_gate import _REAP_INTERVAL_S

    gate = ScopeGate()

    async def main() -> None:
        async with gate.guarded("g"):
            pass

    asyncio.run(main())
    entry = gate._entries["g"]
    assert entry.active == 0
    # 时间戳全部相对当前 monotonic 构造：CI 容器 uptime 可能小于回收
    # 间隔，绝对值 0 会让「距上次回收的间隔」判断跳过本轮回收。
    now = _time.monotonic()
    entry.released_at = now - 10_000
    gate._last_reap = now - (_REAP_INTERVAL_S + 1.0)
    gate._reap(now)
    assert "g" not in gate._entries


def test_record_bypass_counts_and_logs(caplog):
    import logging

    gate = ScopeGate()
    with caplog.at_level(logging.ERROR, logger="quickquip.llm.service_parts.scope_gate"):
        gate.record_bypass("1001", "scope=1001 已有未关闭 Loop loop_x")

    assert gate.bypassed_count == 1
    assert "scope-gate-alarm" in caplog.text


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
