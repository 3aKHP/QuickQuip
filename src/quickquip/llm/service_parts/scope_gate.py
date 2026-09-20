"""同 scope 轮次串行闸门（设计 §5.2「同 scope 串行」的实现补齐）。

群主动/被动、私聊、无聊唤醒与定时 LLM 任务共享 per-scope 互斥：新输入
在 Loop 边界取得执行权，长轮次（如原生生图 4–7 分钟）期间同 scope 的
后续轮次排队等待，而非并发撞上 ``begin_loop`` 的单飞约束（``LoopNotWritable``
→ 无记录路径的记账丢失由此杜绝）。等待方取得执行权后再解析配置、装
配上下文，天然满足 §5.2「取得执行权时再次检查」的时序要求。

进程内存态、无持久队列（§5.2 原文约束：不新增无界持久任务队列）；
进程崩溃后由新进程执行既有 Loop 恢复。``record_bypass`` 计入所有残余
成因（闸门未覆盖路径、上轮崩溃残留未关闭 Loop、跨进程写入）——出现
即需排查，不是常态降级。
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_REAP_INTERVAL_S = 300.0
_IDLE_KEEP_S = 900.0
# 取锁等待超过该秒数（或存在竞争）时记 info 日志，供长轮次排队观测。
_SLOW_ACQUIRE_LOG_S = 1.0


@dataclass(slots=True)
class _GateEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # 最近一次释放的时钟读数；active>0（持有或排队中）的条目永不回收。
    released_at: float = 0.0
    active: int = 0


@dataclass(slots=True)
class GateHold:
    """取得执行权的回执：等待方可据此做过期判断（§5.2 被动触发取消）。"""

    waited_s: float


class ScopeGate:
    """Per-scope 互斥字典；空闲条目定期回收防无界增长。

    ``clock`` 注入时间源（默认 ``time.monotonic``），测试用假时钟推进
    回收判定，不依赖真实时钟基址。
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._entries: dict[str, _GateEntry] = {}
        self._last_reap = clock()
        self.bypassed_count: int = 0

    @property
    def tracked_scope_count(self) -> int:
        """当前跟踪的 scope 条目数（持有/排队/空闲含未回收）。"""
        return len(self._entries)

    def record_bypass(self, scope_key: str, detail: str) -> None:
        """单飞约束仍在 LoopNotWritable 上撞车的残余成因告警。

        可能成因：闸门未覆盖的生成路径、上轮崩溃残留未关闭 Loop、跨
        进程写入。出现即需排查，不是常态降级。
        """
        self.bypassed_count += 1
        logger.error(
            "[scope-gate-alarm] LoopNotWritable 旁路 #%d scope=%s：该轮退回无"
            "记录路径（成因待排查：闸门外路径/崩溃残留/跨进程写入；%s）",
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
    async def guarded(self, scope_key: str) -> AsyncIterator[GateHold]:
        now = self._clock()
        self._reap(now)
        entry = self._entries.get(scope_key)
        if entry is None:
            entry = _GateEntry()
            self._entries[scope_key] = entry
        # active 覆盖「排队中 + 持有中」全程：持有期内也绝不被回收，
        # 否则回收后新建的锁会与在持锁并发放行。
        entry.active += 1
        try:
            wait_start = self._clock()
            contended = entry.lock.locked()
            await entry.lock.acquire()
            waited_s = self._clock() - wait_start
            if contended or waited_s > _SLOW_ACQUIRE_LOG_S:
                logger.info(
                    "scope gate acquired scope=%s wait_s=%.1f", scope_key, waited_s
                )
            try:
                yield GateHold(waited_s=waited_s)
            finally:
                entry.released_at = self._clock()
                entry.lock.release()
        finally:
            entry.active -= 1
