from __future__ import annotations

from collections import OrderedDict, deque


class RecentMessageDeduper:
    def __init__(self, max_groups: int = 1024, max_ids_per_group: int = 256):
        self.max_groups = max_groups
        self.max_ids_per_group = max_ids_per_group
        self.group_ids: OrderedDict[str, deque[str]] = OrderedDict()
        self.group_seen: dict[str, set[str]] = {}

    def _touch_group(self, group_key: str) -> None:
        if group_key in self.group_ids:
            self.group_ids.move_to_end(group_key)

    def _prune_groups(self) -> None:
        while len(self.group_ids) > self.max_groups:
            group_key, queue = self.group_ids.popitem(last=False)
            self.group_seen.pop(group_key, None)

    def is_duplicate(self, group_id: int | str, message_id: int | str | None) -> bool:
        if message_id is None:
            return False

        group_key = str(group_id)
        message_key = str(message_id)
        queue = self.group_ids.get(group_key)
        seen = self.group_seen.get(group_key)

        if queue is None or seen is None:
            queue = deque()
            seen = set()
            self.group_ids[group_key] = queue
            self.group_seen[group_key] = seen

        self._touch_group(group_key)
        self._prune_groups()

        if message_key in seen:
            return True

        queue.append(message_key)
        seen.add(message_key)
        while len(queue) > self.max_ids_per_group:
            removed = queue.popleft()
            seen.discard(removed)
        return False
