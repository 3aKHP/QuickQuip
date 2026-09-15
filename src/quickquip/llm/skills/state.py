"""per-会话 Skill 激活状态（纯进程内存，不落库）。

key = (会话 scope, skill name)，value = 激活时的正文内容 hash。重启丢失
可接受：注入文本留在会话历史里，模型需要时会重新激活——同 hash 去重
只防同会话重复注入。
"""

from __future__ import annotations


class SkillActivationState:
    """(scope, name) → content hash 的激活登记表。"""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], str] = {}

    def is_duplicate(self, scope: str, name: str, content_hash: str) -> bool:
        return self._records.get((scope, name)) == content_hash

    def record(self, scope: str, name: str, content_hash: str) -> None:
        self._records[(scope, name)] = content_hash

    def is_active(self, scope: str, name: str) -> bool:
        return (scope, name) in self._records

    def clear_scope(self, scope: str) -> None:
        """会话上下文作废（清空/纪元推进）时抹掉该 scope 的全部激活登记。"""
        doomed = [key for key in self._records if key[0] == scope]
        for key in doomed:
            del self._records[key]

    def activated_names(self, scope: str) -> list[str]:
        return sorted(name for key_scope, name in self._records if key_scope == scope)
