from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from quickquip.common.persistence import load_json, save_json


@dataclass
class GroupStats:
    total_messages: int = 0
    user_messages: dict[str, int] = field(default_factory=dict)
    user_names: dict[str, str] = field(default_factory=dict)
    rule_triggers: dict[str, int] = field(default_factory=dict)


class GroupStatsTracker:
    def __init__(self, max_groups: int = 1024):
        self.max_groups = max_groups
        self.stats: OrderedDict[str, GroupStats] = OrderedDict()

    def _touch(self, group_key: str) -> None:
        if group_key in self.stats:
            self.stats.move_to_end(group_key)

    def _prune(self) -> None:
        while len(self.stats) > self.max_groups:
            self.stats.popitem(last=False)

    def _ensure(self, group_key: str) -> GroupStats:
        if group_key not in self.stats:
            self.stats[group_key] = GroupStats()
        self._touch(group_key)
        self._prune()
        return self.stats[group_key]

    def record_message(
        self,
        group_id: int | str,
        user_id: int | str,
        sender_name: str | None = None,
    ) -> None:
        gs = self._ensure(str(group_id))
        gs.total_messages += 1
        user_key = str(user_id)
        gs.user_messages[user_key] = gs.user_messages.get(user_key, 0) + 1
        if sender_name:
            gs.user_names[user_key] = sender_name

    def record_trigger(self, group_id: int | str, rule_name: str) -> None:
        gs = self._ensure(str(group_id))
        gs.rule_triggers[rule_name] = gs.rule_triggers.get(rule_name, 0) + 1

    def get_stats(self, group_id: int | str) -> Optional[GroupStats]:
        return self.stats.get(str(group_id))

    def reset(self, group_id: int | str) -> None:
        self.stats.pop(str(group_id), None)

    def format_stats(
        self,
        group_id: int | str,
        name_resolver: dict[str, str] | None = None,
    ) -> str:
        gs = self.get_stats(group_id)
        if gs is None or gs.total_messages == 0:
            return "暂无统计数据"

        lines = [f"群聊统计\n消息总数：{gs.total_messages}"]

        if gs.user_messages:
            top_users = sorted(gs.user_messages.items(), key=lambda x: -x[1])[:5]
            lines.append("活跃用户 Top 5：")
            for rank, (uid, count) in enumerate(top_users, 1):
                resolver = name_resolver if name_resolver is not None else gs.user_names
                display = resolver.get(uid, uid)
                lines.append(f"  {rank}. {display} — {count} 条")

        if gs.rule_triggers:
            top_rules = sorted(gs.rule_triggers.items(), key=lambda x: -x[1])[:5]
            lines.append("规则触发 Top 5：")
            for rank, (rule, count) in enumerate(top_rules, 1):
                lines.append(f"  {rank}. {rule} — {count} 次")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            gid: {
                "total_messages": gs.total_messages,
                "user_messages": gs.user_messages,
                "user_names": gs.user_names,
                "rule_triggers": gs.rule_triggers,
            }
            for gid, gs in self.stats.items()
        }

    def from_dict(self, data: dict) -> None:
        self.stats.clear()
        for gid, entry in data.items():
            self.stats[str(gid)] = GroupStats(
                total_messages=entry.get("total_messages", 0),
                user_messages=entry.get("user_messages", {}),
                user_names=entry.get("user_names", {}),
                rule_triggers=entry.get("rule_triggers", {}),
            )

    def save(self, path: str | Path) -> None:
        save_json(path, self.to_dict())

    def load(self, path: str | Path) -> None:
        data = load_json(path)
        if data is not None:
            self.from_dict(data)
