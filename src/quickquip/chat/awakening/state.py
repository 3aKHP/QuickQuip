"""唤醒运行时状态域：进程内状态单例（延长会话、沉寂时间戳、判定缓存）。"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic

from quickquip.chat.config import RECENT_CONTEXT_TTL_SECONDS


@dataclass(frozen=True, slots=True)
class AwakeningExtendSession:
    timestamp: float
    source: str = "explicit_llm"


class BotMessageCache:
    """Per-group cache of recent bot reply texts for relevance checking.

    Entries older than the recent-context TTL (monotonic clock) are evicted
    lazily on read; the window is shared with ``RecentMessageBuffer``.
    """

    __slots__ = ("_messages", "_ttl_seconds")
    _MAX_PER_GROUP = 5

    def __init__(self, *, ttl_seconds: float = RECENT_CONTEXT_TTL_SECONDS) -> None:
        self._messages: dict[str, deque[tuple[str, float]]] = {}
        self._ttl_seconds = ttl_seconds

    def add(self, group_id: int | str, text: str, *, now: float | None = None) -> None:
        gid = str(group_id)
        if gid not in self._messages:
            self._messages[gid] = deque(maxlen=self._MAX_PER_GROUP)
        stripped = text.strip()
        if stripped:
            self._messages[gid].append((stripped, monotonic() if now is None else now))

    def get_recent(self, group_id: int | str, *, now: float | None = None) -> list[str]:
        gid = str(group_id)
        queue = self._messages.get(gid)
        if queue is None:
            return []
        current = monotonic() if now is None else now
        while queue and (current - queue[0][1]) > self._ttl_seconds:
            queue.popleft()
        if not queue:
            del self._messages[gid]
            return []
        return [text for text, _ in queue]

    def clear_group(self, group_id: int | str) -> None:
        self._messages.pop(str(group_id), None)


class AwakeningState:
    __slots__ = (
        "_extend_sessions", "_last_message_times", "_last_boredom_trigger",
        "bot_messages", "_llm_cache",
    )

    _LLM_CACHE_TTL = 60.0
    _LLM_CACHE_MAX = 256

    def __init__(self) -> None:
        self._extend_sessions: dict[str, dict[str, AwakeningExtendSession]] = {}
        self._last_message_times: dict[str, float] = {}
        self._last_boredom_trigger: dict[str, float] = {}
        self.bot_messages = BotMessageCache()
        self._llm_cache: dict[tuple[str, str, str], tuple[bool, float]] = {}

    def record_message(self, group_id: int | str) -> None:
        self._last_message_times[str(group_id)] = monotonic()

    def mark_awakened(
        self, group_id: int | str, user_id: int | str, source: str = "explicit_llm"
    ) -> None:
        gid = str(group_id)
        uid = str(user_id)
        if gid not in self._extend_sessions:
            self._extend_sessions[gid] = {}
        self._extend_sessions[gid][uid] = AwakeningExtendSession(
            timestamp=monotonic(),
            source=source.strip() or "explicit_llm",
        )

    def is_in_extend_window(self, group_id: int | str, user_id: int | str, duration: int) -> bool:
        if duration <= 0:
            return False
        gid = str(group_id)
        uid = str(user_id)
        sessions = self._extend_sessions.get(gid)
        if sessions is None:
            return False
        session = sessions.get(uid)
        if session is None:
            return False
        return session.source == "explicit_llm" and (monotonic() - session.timestamp) < duration

    def get_group_silence_seconds(self, group_id: int | str) -> float | None:
        """群沉寂秒数；本进程未观察到该群消息时返回 None（未知），
        未知状态不允许无聊唤醒。"""
        ts = self._last_message_times.get(str(group_id))
        if ts is None:
            return None
        return monotonic() - ts

    def can_trigger_boredom(self, group_id: int | str, check_interval: int) -> bool:
        ts = self._last_boredom_trigger.get(str(group_id))
        if ts is None:
            return True
        return (monotonic() - ts) >= check_interval

    def mark_boredom_triggered(self, group_id: int | str) -> None:
        self._last_boredom_trigger[str(group_id)] = monotonic()

    def clear_boredom_state(self, group_id: int | str) -> None:
        """清除群的沉寂与冷却状态（群取消无聊唤醒 opt-in 时调用）。"""
        gid = str(group_id)
        self._last_message_times.pop(gid, None)
        self._last_boredom_trigger.pop(gid, None)

    def llm_cache_get(self, rule: str, group_id: int | str, text: str) -> bool | None:
        key = (rule, str(group_id), text)
        entry = self._llm_cache.get(key)
        if entry is None:
            return None
        result, ts = entry
        if (monotonic() - ts) > self._LLM_CACHE_TTL:
            del self._llm_cache[key]
            return None
        return result

    def llm_cache_set(self, rule: str, group_id: int | str, text: str, result: bool) -> None:
        if len(self._llm_cache) >= self._LLM_CACHE_MAX:
            now = monotonic()
            expired = [
                k for k, (_, ts) in self._llm_cache.items() if (now - ts) > self._LLM_CACHE_TTL
            ]
            for k in expired:
                del self._llm_cache[k]
            if len(self._llm_cache) >= self._LLM_CACHE_MAX:
                oldest_key = min(self._llm_cache, key=lambda k: self._llm_cache[k][1])
                del self._llm_cache[oldest_key]
        self._llm_cache[(rule, str(group_id), text)] = (result, monotonic())

    def prune_stale(self, max_age: float = 7200) -> None:
        """只清理延长会话。沉寂时间戳与群级冷却**不做固定时限淘汰**：
        较大的 boredom_silence_seconds 会被提前满足（旧实现两小时即丢状态，
        使沉寂回到未知），取消 opt-in 的清除由 clear_boredom_state 显式负责。
        每群仅各一个浮点条目，不淘汰无增长风险。"""
        now = monotonic()
        for sessions in self._extend_sessions.values():
            stale = [
                uid for uid, session in sessions.items() if (now - session.timestamp) > max_age
            ]
            for uid in stale:
                del sessions[uid]
        stale_groups = [gid for gid, sessions in self._extend_sessions.items() if not sessions]
        for gid in stale_groups:
            del self._extend_sessions[gid]


_state = AwakeningState()


def get_state() -> AwakeningState:
    return _state
