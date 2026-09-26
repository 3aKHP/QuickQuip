"""per-会话 Skill 激活状态（纯进程内存，不落库）。

key = (会话 scope, skill name)，value = (激活时正文 hash, 激活时刻的会话
尾部行 id)。重启丢失可接受：注入文本留在会话历史里，模型需要时会重新
激活——同 hash 去重只防同会话重复注入。

去重表不得活得比可见历史长（a9a1eed 不变量）：激活正文随激活轮 loop 的
工具结果落库，窗口收缩（纪元推进、/llm context_limit 行数兜底）把它移出
可见窗口后，登记必须随之失效，否则重新激活只会拿到"已激活"短文本而正文
已不可见。纪元推进路径在推进事件时整体清登记；锚点推进类收缩由
``drop_outdated`` 巡检兜底——登记的尾部行 id 早于生效锚点即意味着激活轮
已出窗（误差方向安全：巡检偏早清除只会多注入一次正文，不会缺注入）。
词表归档与投影降级类收缩（行不动、发给模型的可见面变）不在巡检内，
残留登记的自救是模型自行 ``read_skill_resource`` 读取正文。
"""

from __future__ import annotations

_TAIL_UNKNOWN = 0


class SkillActivationState:
    """(scope, name) → (content hash, 激活时会话尾部行 id) 的激活登记表。"""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], tuple[str, int]] = {}

    def is_duplicate(self, scope: str, name: str, content_hash: str) -> bool:
        return self._records.get((scope, name), ("", _TAIL_UNKNOWN))[0] == content_hash

    def record(
        self, scope: str, name: str, content_hash: str, tail_row_id: int = _TAIL_UNKNOWN
    ) -> None:
        self._records[(scope, name)] = (content_hash, max(int(tail_row_id), 0))

    def is_active(self, scope: str, name: str) -> bool:
        return (scope, name) in self._records

    def clear_scope(self, scope: str) -> None:
        """会话上下文作废（清空/纪元推进）时抹掉该 scope 的全部激活登记。"""
        doomed = [key for key in self._records if key[0] == scope]
        for key in doomed:
            del self._records[key]

    def drop_outdated(self, scope: str, anchor_row_id: int) -> None:
        """窗口守卫：登记的激活尾部早于生效锚点 → 激活轮已出窗，清登记。

        尾部未知的旧登记（tail_row_id=0）不参与判定，维持既有行为。
        """
        doomed = [
            key
            for key, (_hash, tail) in self._records.items()
            if key[0] == scope and tail > _TAIL_UNKNOWN and tail < anchor_row_id
        ]
        for key in doomed:
            del self._records[key]

    def activated_names(self, scope: str) -> list[str]:
        return sorted(name for key_scope, name in self._records if key_scope == scope)
