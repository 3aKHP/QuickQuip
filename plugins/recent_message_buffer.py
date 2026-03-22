from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from time import time


@dataclass(slots=True)
class RecentMessage:
    user_id: str
    sender_name: str
    text: str
    created_at: float


class RecentMessageBuffer:
    def __init__(
        self,
        *,
        max_groups: int = 1024,
        max_messages_per_group: int = 20,
        ttl_seconds: int = 1800,
    ):
        self.max_groups = max_groups
        self.max_messages_per_group = max_messages_per_group
        self.ttl_seconds = ttl_seconds
        self.messages: OrderedDict[str, deque[RecentMessage]] = OrderedDict()

    def _now(self, now_ts: float | None = None) -> float:
        return time() if now_ts is None else now_ts

    def _touch_group(self, group_key: str) -> None:
        if group_key in self.messages:
            self.messages.move_to_end(group_key)

    def _prune_groups(self) -> None:
        while len(self.messages) > self.max_groups:
            self.messages.popitem(last=False)

    def _prune_expired(self, group_key: str, now_ts: float) -> None:
        queue = self.messages.get(group_key)
        if queue is None:
            return
        expires_before = now_ts - self.ttl_seconds
        while queue and queue[0].created_at < expires_before:
            queue.popleft()
        if not queue:
            self.messages.pop(group_key, None)

    def add_message(
        self,
        group_id: int | str,
        user_id: int | str,
        sender_name: str,
        text: str,
        *,
        now_ts: float | None = None,
    ) -> None:
        normalized = text.strip()
        if not normalized:
            return

        current_ts = self._now(now_ts)
        group_key = str(group_id)
        self._prune_expired(group_key, current_ts)

        queue = self.messages.get(group_key)
        if queue is None:
            queue = deque(maxlen=self.max_messages_per_group)
            self.messages[group_key] = queue

        queue.append(
            RecentMessage(
                user_id=str(user_id),
                sender_name=sender_name.strip() or str(user_id),
                text=normalized,
                created_at=current_ts,
            )
        )
        self._touch_group(group_key)
        self._prune_groups()

    def list_recent(
        self,
        group_id: int | str,
        *,
        limit: int | None = None,
        now_ts: float | None = None,
    ) -> list[dict[str, str]]:
        current_ts = self._now(now_ts)
        group_key = str(group_id)
        self._prune_expired(group_key, current_ts)
        queue = self.messages.get(group_key)
        if queue is None:
            return []

        self._touch_group(group_key)
        items = list(queue)
        if limit is not None:
            items = items[-int(limit):]
        return [
            {
                "user_id": item.user_id,
                "sender_name": item.sender_name,
                "text": item.text,
            }
            for item in items
        ]
