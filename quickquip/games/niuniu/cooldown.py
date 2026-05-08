"""Thread-safe, auto-expiring cooldown tracker for niuniu actions."""

import threading
import time


class CooldownTracker:
    """Per-user cooldown tracker with automatic expiry cleanup."""

    def __init__(self):
        self._cd: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, uid: str) -> float:
        """Return remaining CD seconds, or 0 if ready/expired."""
        with self._lock:
            until = self._cd.get(uid, 0)
            remaining = until - time.time()
            if remaining <= 0:
                self._cd.pop(uid, None)
                return 0.0
            return remaining

    def set(self, uid: str, seconds: float) -> None:
        """Set a cooldown for *uid* lasting *seconds* from now."""
        with self._lock:
            self._cd[uid] = time.time() + seconds

    def clear(self, uid: str) -> None:
        """Remove cooldown entry for *uid*."""
        with self._lock:
            self._cd.pop(uid, None)


# Global singleton instances
glue_cd = CooldownTracker()
fence_cd = CooldownTracker()
fenced_cd = CooldownTracker()
arrested_cd = CooldownTracker()
