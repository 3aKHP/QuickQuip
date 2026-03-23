import random
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE, BEIJING_TIME_FORMAT, TEXT_REPLY_RULES


def build_rule_context(user_id: int | str, sender_name: str, now: Optional[datetime] = None) -> dict:
    current_dt = now or datetime.now(ZoneInfo(BEIJING_TIMEZONE))
    return {
        "current_time": current_dt.strftime(BEIJING_TIME_FORMAT),
        "user_id": str(user_id),
        "sender_name": sender_name,
    }


def replace_regex_groups(template: str, match: re.Match) -> str:
    def repl(group_match: re.Match) -> str:
        group_index = int(group_match.group(1))
        try:
            return match.group(group_index) or ""
        except IndexError:
            return ""

    return re.sub(r"\$(\d+)", repl, template)


def select_reply_template(rule: dict) -> str:
    templates = rule.get("reply_templates")
    if not templates:
        return rule["reply_template"]
    weights = [t.get("weight", 1) for t in templates]
    chosen = random.choices(templates, weights=weights, k=1)[0]
    return chosen["template"]


def render_rule_reply(template: str, context: dict, match: re.Match) -> str:
    rendered = replace_regex_groups(template, match)
    return rendered.format(**context)


def is_rule_match_allowed(rule: dict, match: re.Match) -> bool:
    blocked_groups = rule.get("blocked_groups", {})
    for group_index, blocked_values in blocked_groups.items():
        group_value = match.group(int(group_index))
        if group_value in blocked_values:
            return False

    blocked_named_groups = rule.get("blocked_named_groups", {})
    for group_name, blocked_values in blocked_named_groups.items():
        group_value = match.groupdict().get(group_name)
        if group_value in blocked_values:
            return False

    return True


def match_text_rule(
    text: str,
    user_id: int | str,
    sender_name: str,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    base_context = build_rule_context(user_id, sender_name, now=now)
    matched_rules = []

    for rule_index, rule in enumerate(TEXT_REPLY_RULES):
        for pattern in rule["patterns"]:
            match = re.search(pattern, text)
            if not match:
                continue
            if not is_rule_match_allowed(rule, match):
                continue

            context = {**base_context, **match.groupdict()}
            template = select_reply_template(rule)
            matched_rules.append(
                {
                    "rule_name": rule["name"],
                    "rate_limit_key": rule.get("rate_limit_key", rule["name"]),
                    "reply": render_rule_reply(template, context, match),
                    "context": context,
                    "priority": int(rule.get("priority", 0)),
                    "rule_index": rule_index,
                }
            )
            break

    if not matched_rules:
        return None

    matched_rules.sort(key=lambda item: (-item["priority"], item["rule_index"]))
    best_match = matched_rules[0]
    best_match.pop("rule_index", None)
    return best_match
