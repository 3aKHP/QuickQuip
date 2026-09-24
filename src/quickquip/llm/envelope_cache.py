"""最近一封【轮次上下文】信封的六段 token 分解缓存（进程内旁路）。

与纪元锚点同生命周期语义：真值在 bot 进程内存，不落库（信封组装时渲染、
逐轮全价重算是设计契约）；本缓存只服务 Web Admin 纪元看板的"信封构成条"
实时态，经 ``epoch_snapshot`` action 导出。record 只保留每键最近一次。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from quickquip.llm.epoch import EpochKey
from quickquip.llm.token_estimate import estimate_tokens

# 分解口径的段序（与 prompting.build_turn_envelope_segments 的键序一致）。
SEGMENT_KEYS = ("time", "festival", "participants", "mentions", "memories", "vocab")


@dataclass(frozen=True, slots=True)
class EnvelopeBreakdown:
    parts: dict[str, int]
    total_tokens: int
    recorded_at: float


class EnvelopeBreakdownCache:
    """per-EpochKey 的最近一封信封分解（写一侧读一侧，GIL 下字典赋值原子）。"""

    def __init__(self, *, clock=time.time) -> None:
        self._clock = clock
        self._entries: dict[EpochKey, EnvelopeBreakdown] = {}

    def record(self, key: EpochKey, parts: dict[str, str]) -> None:
        """装配后调用：逐段估 token 并覆盖该键的最近一次分解。"""
        tokens = {name: estimate_tokens(text) for name, text in parts.items()}
        self._entries[key] = EnvelopeBreakdown(
            parts=tokens,
            total_tokens=sum(tokens.values()),
            recorded_at=self._clock(),
        )

    def get(self, key: EpochKey) -> EnvelopeBreakdown | None:
        return self._entries.get(key)

    def clear_scope(self, scope_key: str) -> None:
        """抹除某会话 scope 的全部缓存键。

        清空上下文/私聊归档时纪元键被 reset，信封缓存若保留旧值会让看板
        继续展示一封语义上已失效的信封；与锚点同生命周期，一并抹除。
        """
        doomed = [key for key in self._entries if key.scope_key == scope_key]
        for key in doomed:
            del self._entries[key]

    def export(self) -> list[dict[str, object]]:
        """快照导出（epoch_snapshot 消费）：值拷贝，避免消费方读到可变内部态。

        list() 先把 items 原子快照（C 层循环不释放 GIL）：导出经
        asyncio.to_thread 在 worker 线程执行，迭代期间事件循环线程
        record/clear 不致 RuntimeError。
        """
        return [
            {
                "scope_key": key.scope_key,
                "provider_id": key.provider_id,
                "model": key.model,
                "parts": dict(entry.parts),
                "total_tokens": entry.total_tokens,
                "recorded_at": entry.recorded_at,
            }
            for key, entry in list(self._entries.items())
        ]
