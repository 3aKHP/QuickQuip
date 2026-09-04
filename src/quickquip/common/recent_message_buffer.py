from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(slots=True)
class RecentMessage:
    user_id: str
    sender_name: str
    canonical_name: str
    text: str
    created_at: float
    message_id: str = ""
    image_urls: list[str] = field(default_factory=list)


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
        # group_key -> 上次补丁服役时刻（created_at 水位）；读即服役语义见 list_patch
        self._patch_cursors: dict[str, float] = {}

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
        canonical_name: str,
        text: str,
        *,
        message_id: str = "",
        image_urls: list[str] | None = None,
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

        normalized_image_urls = [u.strip() for u in (image_urls or []) if u.strip()]
        queue.append(
            RecentMessage(
                user_id=str(user_id),
                sender_name=sender_name.strip() or str(user_id),
                canonical_name=canonical_name.strip(),
                text=normalized,
                created_at=current_ts,
                message_id=str(message_id) if message_id else "",
                image_urls=normalized_image_urls,
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
    ) -> list[dict[str, Any]]:
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
                "canonical_name": item.canonical_name,
                "text": item.text,
                "message_id": item.message_id,
                "image_urls": list(item.image_urls),
            }
            for item in items
        ]

    def list_patch(
        self,
        group_id: int | str,
        *,
        exclude_message_ids: set[str] | frozenset[str] = frozenset(),
        budget_tokens: int,
        floor_seconds: float,
        token_estimator: Callable[[str], int],
        now_ts: float | None = None,
    ) -> list[dict[str, Any]]:
        """LLM 请求路径专用的增量补丁读取（区别于 list_recent 的全量快照）。

        候选 = （上次服役之后的新消息）∪（floor_seconds 滑动保底窗内的消息），
        剔除 exclude_message_ids（history 已覆盖者与当前触发消息）；
        无 message_id 的消息无法去重、始终保留。
        之后按 token_estimator 从最新往回截到 budget_tokens（至少保留最新一条）。

        本方法不推进游标——调用方在消费后调 note_patch_served（读即服役）。
        返回 dict 在 list_recent 形态上附加 created_at 键。
        """
        current_ts = self._now(now_ts)
        group_key = str(group_id)
        self._prune_expired(group_key, current_ts)
        queue = self.messages.get(group_key)
        if queue is None:
            return []

        self._touch_group(group_key)
        served_until = self._patch_cursors.get(group_key, float("-inf"))
        floor_from = current_ts - floor_seconds
        candidates = [
            item
            for item in queue
            if (item.created_at > served_until or item.created_at >= floor_from)
            and (not item.message_id or item.message_id not in exclude_message_ids)
        ]

        kept: list[RecentMessage] = []
        total = 0
        for item in reversed(candidates):
            cost = max(0, int(token_estimator(item.text)))
            if kept and total + cost > budget_tokens:
                break
            kept.append(item)
            total += cost
        kept.reverse()

        return [
            {
                "user_id": item.user_id,
                "sender_name": item.sender_name,
                "canonical_name": item.canonical_name,
                "text": item.text,
                "message_id": item.message_id,
                "image_urls": list(item.image_urls),
                "created_at": item.created_at,
            }
            for item in kept
        ]

    def note_patch_served(self, group_id: int | str, now_ts: float | None = None) -> None:
        """推进补丁游标到 now（读即服役：失败轮丢失超保底窗的旧补丁，由 floor 兜底）。"""
        group_key = str(group_id)
        self._patch_cursors[group_key] = self._now(now_ts)
        # 游标表不随消息过期自动清，做个廉价上界：超出 max_groups 时丢弃沉寂群的游标
        if len(self._patch_cursors) > self.max_groups:
            for key in list(self._patch_cursors):
                if key not in self.messages:
                    del self._patch_cursors[key]

    def clear_scope(self, group_id: int | str) -> bool:
        group_key = str(group_id)
        self._patch_cursors.pop(group_key, None)
        return self.messages.pop(group_key, None) is not None

    def remove_by_message_id(self, group_id: int | str, message_id: str) -> bool:
        group_key = str(group_id)
        queue = self.messages.get(group_key)
        if queue is None:
            return False
        msg_key = str(message_id)
        remaining = [m for m in queue if m.message_id != msg_key]
        if len(remaining) == len(queue):
            return False
        new_queue: deque[RecentMessage] = deque(remaining, maxlen=self.max_messages_per_group)
        if new_queue:
            self.messages[group_key] = new_queue
        else:
            self.messages.pop(group_key, None)
        return True
