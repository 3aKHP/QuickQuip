from collections import OrderedDict
from pathlib import Path

from quickquip.chat.config import CHAIN_GAME_CONFIGS, CONTEXT_REPLY_RULES, TEXT_REPLY_RULES
from quickquip.common.persistence import load_json, save_json


# 系统/模块规则与历史保留的规则名（保留是为了兼容已有 rule_switch.json）。
# TOML 加载出来的规则名会在模块加载时自动并入 SWITCHABLE_RULES。
_BUILTIN_SWITCHABLE_RULES: set[str] = {
    # 模块级
    "daily_briefing",
    "daily_summary",
    "repeat_follow_read",
    "repeat_trim_last",
    "repeat_same_user_warning",
    "good_girl_chain_start",
    "good_girl_chain_progress",
    "timezone_wake",
    "timezone_sleep",
    "sts_card_le",
    "llm_chat",
    "tieba_random_post",
    "awakening_extend",
    "awakening_interest",
    "awakening_fallback",
    "awakening_boredom",
    "awakening_relevance",
    "awakening_qa",
    # 历史保留（曾在硬编码名单中，可能在旧部署里出现）
    "maggot_arrival",
    "master_protection",
    "huaizhen_oversize",
    "kpl_final",
}


def _collect_config_rule_names() -> set[str]:
    names: set[str] = set()
    for rule in TEXT_REPLY_RULES:
        name = rule.get("name")
        if name:
            names.add(name)
    for rule in CONTEXT_REPLY_RULES:
        name = rule.get("name")
        if name:
            names.add(name)
    for game in CHAIN_GAME_CONFIGS:
        name = game.get("name")
        if name:
            names.add(f"{name}_start")
            names.add(f"{name}_progress")
    return names


SWITCHABLE_RULES: set[str] = set()


def rebuild_switchable_rules() -> None:
    """Repopulate SWITCHABLE_RULES in place from builtin + current TOML-derived rule names."""
    SWITCHABLE_RULES.clear()
    SWITCHABLE_RULES.update(_BUILTIN_SWITCHABLE_RULES)
    SWITCHABLE_RULES.update(_collect_config_rule_names())


rebuild_switchable_rules()


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
