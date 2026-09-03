"""Retry policy and exponential-backoff computation for provider requests.

The retry loop itself lives in :meth:`BaseProviderClient._dispatch_with_retry`
(invoked from ``complete()``); this module only holds the policy value object
and the pure delay computation so both stay trivially unit-testable and free
of provider-layer imports.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from quickquip.llm.config import (
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_RETRY_JITTER,
    DEFAULT_RETRY_MAX_ATTEMPTS,
)


@dataclass(slots=True)
class RetryPolicy:
    """上游 429/5xx/网络错误的自动重试策略。

    ``max_attempts`` 含首次调用；第 n 次重试（0 起）的等待秒数为
    ``base_delay * 2**n * (1 + uniform(0, jitter))``。
    """

    max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS
    base_delay: float = DEFAULT_RETRY_BASE_DELAY
    jitter: float = DEFAULT_RETRY_JITTER

    @classmethod
    def disabled(cls) -> "RetryPolicy":
        """单次尝试策略：供探活/诊断等需要真实失败反馈的调用方使用。"""
        return cls(max_attempts=1, base_delay=0.0, jitter=0.0)


def backoff_delay(
    attempt: int,
    policy: RetryPolicy,
    uniform: Callable[[float, float], float] = random.uniform,
) -> float:
    """第 ``attempt`` 次重试（0 起）前的等待秒数：指数退避 + 乘性随机抖动。"""
    base = policy.base_delay * (2 ** attempt)
    if policy.jitter <= 0:
        return base
    return base * (1 + uniform(0.0, policy.jitter))
