from collections import defaultdict, deque
from time import time


class SlidingWindowRateLimiter:
    def __init__(self, global_limit: int, user_limit: int, window_seconds: int = 60):
        self.global_limit = global_limit
        self.user_limit = user_limit
        self.window_seconds = window_seconds
        self.global_timestamps = deque()
        self.user_timestamps = defaultdict(deque)

    def _prune(self, timestamps: deque, now_ts: float) -> None:
        while timestamps and now_ts - timestamps[0] >= self.window_seconds:
            timestamps.popleft()

    def allow(self, user_id: int | str, now_ts: float | None = None) -> bool:
        current_ts = time() if now_ts is None else now_ts

        self._prune(self.global_timestamps, current_ts)
        user_queue = self.user_timestamps[str(user_id)]
        self._prune(user_queue, current_ts)

        if len(self.global_timestamps) >= self.global_limit:
            return False
        if len(user_queue) >= self.user_limit:
            return False

        self.global_timestamps.append(current_ts)
        user_queue.append(current_ts)
        return True


class KeyedRateLimiter:
    def __init__(self, rule_limits: dict[str, dict], window_seconds: int = 60):
        self.window_seconds = window_seconds
        self.limiters = {
            key: SlidingWindowRateLimiter(
                global_limit=value["global_limit"],
                user_limit=value["user_limit"],
                window_seconds=window_seconds,
            )
            for key, value in rule_limits.items()
        }

    def allow(self, key: str, user_id: int | str, now_ts: float | None = None) -> bool:
        limiter = self.limiters.get(key)
        if limiter is None:
            return True
        return limiter.allow(user_id=user_id, now_ts=now_ts)
