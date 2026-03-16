from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional


@dataclass
class RepeatState:
    text: str
    count: int
    first_sender_id: str
    last_sender_id: str
    all_same_sender: bool = True


class GroupRepeatDetector:
    def __init__(self, max_groups: int = 1024):
        self.max_groups = max_groups
        self.states: OrderedDict[str, RepeatState] = OrderedDict()

    def _trim_last_character(self, text: str) -> str:
        return text[:-1]

    def _touch_state(self, group_key: str) -> None:
        if group_key in self.states:
            self.states.move_to_end(group_key)

    def _prune_states(self) -> None:
        while len(self.states) > self.max_groups:
            self.states.popitem(last=False)

    def process(self, group_id: int | str, user_id: int | str, text: str) -> Optional[dict]:
        normalized_text = text.strip()
        if not normalized_text:
            return None

        group_key = str(group_id)
        user_key = str(user_id)
        state = self.states.get(group_key)

        if state is None or state.text != normalized_text:
            self.states[group_key] = RepeatState(
                text=normalized_text,
                count=1,
                first_sender_id=user_key,
                last_sender_id=user_key,
                all_same_sender=True,
            )
            self._touch_state(group_key)
            self._prune_states()
            return None

        self._touch_state(group_key)
        previous_sender_id = state.last_sender_id
        state.count += 1
        state.last_sender_id = user_key
        state.all_same_sender = state.all_same_sender and user_key == state.first_sender_id

        if state.count == 2:
            if user_key != previous_sender_id:
                return {
                    "reply": normalized_text,
                    "rate_limit_key": "repeat_follow_read",
                    "rule_name": "repeat_follow_read",
                }

            trimmed = self._trim_last_character(normalized_text)
            if not trimmed:
                return None
            return {
                "reply": trimmed,
                "rate_limit_key": "repeat_trim_last",
                "rule_name": "repeat_trim_last",
            }

        if state.count == 4 and state.all_same_sender:
            return {
                "reply": "艾斯比",
                "at_user_id": user_key,
                "rate_limit_key": "repeat_same_user_warning",
                "rule_name": "repeat_same_user_warning",
            }

        return None
