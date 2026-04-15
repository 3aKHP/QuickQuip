from collections import OrderedDict
from pathlib import Path

from quickquip.common.persistence import load_json, save_json


# All switchable rule names (text rules + built-in modules).
SWITCHABLE_RULES = {
    "daily_briefing",
    "daily_summary",
    "divine_arrival",
    "play_target",
    "double_char_ni_de",
    "sandwich_de",
    "like_reply",
    "maggot_arrival",
    "genshin_start",
    "master_protection",
    "huaizhen_oversize",
    "kpl_final",
    "i_do",
    "repeat_follow_read",
    "repeat_trim_last",
    "repeat_same_user_warning",
    "good_girl_chain_start",
    "good_girl_chain_progress",
    "timezone_wake",
    "timezone_sleep",
    "llm_chat",
    "tieba_random_post",
}


class GroupRuleSwitch:
    def __init__(self, max_groups: int = 1024):
        self.max_groups = max_groups
        self.disabled: OrderedDict[str, set[str]] = OrderedDict()

    def _touch(self, group_key: str) -> None:
        if group_key in self.disabled:
            self.disabled.move_to_end(group_key)

    def _prune(self) -> None:
        while len(self.disabled) > self.max_groups:
            self.disabled.popitem(last=False)

    def disable(self, group_id: int | str, rule_name: str) -> bool:
        if rule_name not in SWITCHABLE_RULES:
            return False
        group_key = str(group_id)
        if group_key not in self.disabled:
            self.disabled[group_key] = set()
        self._touch(group_key)
        self._prune()
        self.disabled[group_key].add(rule_name)
        return True

    def enable(self, group_id: int | str, rule_name: str) -> bool:
        if rule_name not in SWITCHABLE_RULES:
            return False
        group_key = str(group_id)
        disabled_set = self.disabled.get(group_key)
        if disabled_set is None:
            return True
        disabled_set.discard(rule_name)
        if not disabled_set:
            self.disabled.pop(group_key, None)
        return True

    def is_enabled(self, group_id: int | str, rule_name: str) -> bool:
        disabled_set = self.disabled.get(str(group_id))
        if disabled_set is None:
            return True
        return rule_name not in disabled_set

    def list_disabled(self, group_id: int | str) -> set[str]:
        return set(self.disabled.get(str(group_id), set()))

    def format_rules(self, group_id: int | str) -> str:
        disabled_set = self.list_disabled(group_id)
        lines = ["规则列表："]
        for rule in sorted(SWITCHABLE_RULES):
            status = "OFF" if rule in disabled_set else "ON"
            lines.append(f"  [{status}] {rule}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {gid: sorted(rules) for gid, rules in self.disabled.items()}

    def from_dict(self, data: dict) -> None:
        self.disabled.clear()
        for gid, rules in data.items():
            valid = set(rules) & SWITCHABLE_RULES
            if valid:
                self.disabled[str(gid)] = valid

    def save(self, path: str | Path) -> None:
        save_json(path, self.to_dict())

    def load(self, path: str | Path) -> None:
        data = load_json(path)
        if data is not None:
            self.from_dict(data)
