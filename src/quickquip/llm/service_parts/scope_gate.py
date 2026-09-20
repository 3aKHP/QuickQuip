"""同 scope 轮次串行闸门（设计 §5.2「同 scope 串行」的实现补齐）。

群主动/被动、私聊、无聊唤醒与定时 LLM 任务共享 per-scope 互斥：新输入
在 Loop 边界取得执行权，长轮次（如原生生图 4–7 分钟）期间同 scope 的
后续轮次排队等待，而非并发撞上 ``begin_loop`` 的单飞约束（``LoopNotWritable``
→ 无记录路径的记账丢失由此杜绝）。等待方取得执行权后再解析配置、装
配上下文，天然满足 §5.2「取得执行权时再次检查」的时序要求。

进程内存态、无持久队列（§5.2 原文约束：不新增无界持久任务队列）；
进程崩溃后由新进程执行既有 Loop 恢复。闸门被绕过（仍出现
LoopNotWritable）时计入旁路计数——那是编程错误告警，不是常态降级。
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_REAP_INTERVAL_S = 300.0
_IDLE_KEEP_S = 900.0


@dataclass(slots=True)
class _GateEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # 最近一次释放的单调时钟；active>0（持有或排队中）的条目永不回收。
    released_at: float = 0.0
    active: int = 0


class ScopeGate:
    """Per-scope 互斥字典；空闲条目定期回收防无界增长。"""

    def __init__(self) -> None:
        self._entries: dict[str, _GateEntry] = {}
        self._last_reap = time.monotonic()
        self.bypassed_count: int = 0

    def record_bypass(self, scope_key: str, detail: str) -> None:
        """闸门旁路告警：begin_loop 仍在单飞约束上撞车即为编程错误。"""
        self.bypassed_count += 1
        logger.error(
            "[scope-gate-alarm] LoopNotWritable 旁路 #%d scope=%s：闸门应已串行化，"
            "该轮退回无记录路径（%s）",
            self.bypassed_count, scope_key, detail,
        )

    def _reap(self, now: float) -> None:
        if now - self._last_reap < _REAP_INTERVAL_S:
            return
        self._last_reap = now
        for key, entry in list(self._entries.items()):
            if entry.active == 0 and now - entry.released_at > _IDLE_KEEP_S:
                del self._entries[key]

    @asynccontextmanager
    async def guarded(self, scope_key: str):
        self._reap(time.monotonic())
        entry = self._entries.get(scope_key)
        if entry is None:
            entry = _GateEntry()
            self._entries[scope_key] = entry
        # active 覆盖「排队中 + 持有中」全程：持有期内也绝不被回收，
        # 否则回收后新建的锁会与在持锁并发放行。
        entry.active += 1
        try:
            wait_start = time.monotonic()
            contended = entry.lock.locked()
            await entry.lock.acquire()
            wait_ms = (time.monotonic() - wait_start) * 1000
            if contended or wait_ms > 1000.0:
                logger.info(
                    "scope gate acquired scope=%s wait_ms=%.0f", scope_key, wait_ms
                )
            try:
                yield
            finally:
                entry.released_at = time.monotonic()
                entry.lock.release()
        finally:
            entry.active -= 1
