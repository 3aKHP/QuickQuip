"""Auto-memory extraction mixin for :class:`quickquip.llm.service.LLMService`.

Extracted from ``service.py`` as an independent sub-domain: quality gates +
batch trigger + multi-turn context + fixed-confidence store, plus the
per-scope turn counter and success/failure tallies.

The mixin depends on the host class providing ``self.config``,
``self.store`` and ``self.quick_judge`` (all supplied by ``LLMService``).
State is initialised via :meth:`AutoMemoryMixin._init_auto_memory`, which
the host class must call from its own ``__init__``.

Note: ``HealthMixin.build_health_report`` reads ``self._auto_memory_*``
attributes populated here, so ``AutoMemoryMixin`` must stay in the MRO
and ``_init_auto_memory()`` must be called before any health report is
built.
"""
from __future__ import annotations

import logging
from collections import OrderedDict

from quickquip.common.json_utils import extract_json_object
from quickquip.llm.service_parts.constants import MAX_STORED_MEMORY_ITEMS
from quickquip.llm.usage import set_usage_scope

logger = logging.getLogger(__name__)

# ── auto-memory tuning constants ────────────────────────────────────
_AUTO_MEMORY_MIN_USER_CHARS = 8
_AUTO_MEMORY_MIN_ASSISTANT_CHARS = 20
_AUTO_MEMORY_EXTRACT_EVERY_N = 10
_AUTO_MEMORY_CONTEXT_TURNS = 10
_AUTO_MEMORY_DEFAULT_CONFIDENCE = 0.5
_AUTO_MEMORY_DEDUP_THRESHOLD = 0.7
_AUTO_MEMORY_TURN_CACHE_MAX = 2048

_AUTO_MEMORY_DEFAULT_PROMPT = (
    "你是一个保守的群聊记忆助手。你的任务是：只有当对话中**明确出现了**关于发言者的稳定长期事实时，才记录下来。\n"
    "\n"
    "以下是唯一应该记录的内容类型：\n"
    "- 身份信息：职业、专业、所在城市、年龄段（发言者明确说出才算）\n"
    "- 偏好与兴趣：喜欢或讨厌的具体事物、爱好\n"
    "- 能力与经历：掌握的技能、做过的事\n"
    "\n"
    "以下内容**绝对不要**记录：\n"
    "- 闲聊、寒暄、吐槽、搞笑段子\n"
    "- 临时话题（今天吃了什么、天气如何）\n"
    "- 假设、玩笑、反话、玩梗\n"
    "- 不确定是否属于发言者本人的内容\n"
    "- 仅仅因为 bot 的回复提到某个话题就推断用户有相关特征\n"
    "\n"
    "核心原则：**宁可不记，不可记错。** 如果你不确定某条事实是否值得记住，就不要记。\n"
    "\n"
    "格式要求：\n"
    "- 每条事实必须以群友名开头，如「小明是程序员，常用 Python」\n"
    "- 不要用「该用户」「某人」「TA」等模糊指代\n"
    "- 每条事实不超过 40 字\n"
    "\n"
    "只回复 JSON：\n"
    '{"memories": ["事实1", "事实2"]}\n'
    "没有值得记住的内容时回 {\"memories\": []}\n"
    "大部分情况下你应该返回空数组。"
)


def _is_duplicate_memory(new_content: str, existing_contents: list[str]) -> bool:
    """Check character overlap against existing memories (bi-directional min denominator)."""
    new_chars = set(new_content)
    if len(new_chars) < 3:
        return True
    for old in existing_contents:
        old_chars = set(old)
        if not old_chars:
            continue
        min_len = min(len(new_chars), len(old_chars))
        if min_len == 0:
            continue
        overlap = len(new_chars & old_chars) / min_len
        if overlap > _AUTO_MEMORY_DEDUP_THRESHOLD:
            return True
    return False


class AutoMemoryMixin:
    """Conservative auto-memory extraction (runs as a background task).

    Design (v1.0.2 conservative rewrite):

    1. Quality gates: both user and assistant messages must be substantive.
    2. Batch trigger: only runs every N-th turn per scope, not every turn.
    3. Multi-turn context: passes the last several conversation messages so
       the judge can distinguish one-off remarks from stable facts.
    4. Fixed confidence: all auto memories are stored at 0.5; the LLM does
       not self-score.
    5. Bi-directional dedup: character overlap uses min(len) denominator.
    """

    def _init_auto_memory(self) -> None:
        """Initialise auto-memory state. Call once from the host ``__init__``."""
        self._auto_memory_turns: OrderedDict[str, int] = OrderedDict()
        self._auto_memory_successes = 0
        self._auto_memory_failures = 0

    async def _extract_auto_memory(
        self,
        *,
        scope_key: str,
        user_id: int | str,
        sender_name: str,
        canonical_name: str = "",
        user_text: str,
        assistant_text: str,
    ) -> None:
        set_usage_scope("auto_memory", group_id=scope_key)
        try:
            # ── quality gates ──────────────────────────────────────
            if not (user_text.strip() and assistant_text.strip()):
                return
            if len(user_text.strip()) < _AUTO_MEMORY_MIN_USER_CHARS:
                return
            if len(assistant_text.strip()) < _AUTO_MEMORY_MIN_ASSISTANT_CHARS:
                return

            # ── batch trigger ───────────────────────────────────────
            turn_count = self._auto_memory_turns.get(scope_key, 0) + 1
            if scope_key in self._auto_memory_turns:
                self._auto_memory_turns.move_to_end(scope_key)
            elif len(self._auto_memory_turns) >= _AUTO_MEMORY_TURN_CACHE_MAX:
                self._auto_memory_turns.popitem(last=False)
            self._auto_memory_turns[scope_key] = turn_count
            if turn_count % _AUTO_MEMORY_EXTRACT_EVERY_N != 0:
                return

            # ── build context ───────────────────────────────────────
            judge_prompt = (
                self.config.runtime.auto_memory_prompt.strip()
                or _AUTO_MEMORY_DEFAULT_PROMPT
            )

            history = self.store.list_recent_conversation_messages(
                scope_key,
                limit=_AUTO_MEMORY_CONTEXT_TURNS * 2,
            )
            context_parts: list[str] = []
            seen = 0
            for msg in reversed(history):
                role = msg.get("role", "")
                name = msg.get("canonical_name") or msg.get("sender_name", "?")
                content = str(msg.get("raw_content") or msg.get("content", "")).strip()
                if not content:
                    continue
                tag = {"user": "群友", "assistant": "bot"}.get(role, role)
                context_parts.append(f"[{tag}] {name}: {content[:200]}")
                seen += 1
                if seen >= _AUTO_MEMORY_CONTEXT_TURNS:
                    break
            context_parts.reverse()

            display_name = canonical_name or sender_name
            name_line = f"当前要评估的发言者：{display_name}"
            if canonical_name and sender_name and canonical_name != sender_name:
                name_line += f"（QQ昵称：{sender_name}）"

            context_block = "\n".join(context_parts) if context_parts else "（无上下文）"
            full_prompt = (
                f"{judge_prompt}\n\n"
                f"## 最近对话上下文（用于判断事实是否稳定、非偶然）\n"
                f"{context_block}\n\n"
                f"## 当前发言\n"
                f"{name_line}\n"
                f"TA 的发言：{user_text}\n"
                f"你的回复：{assistant_text}"
            )

            # ── judge ───────────────────────────────────────────────
            raw = await self.quick_judge(
                full_prompt,
                max_tokens=self.config.runtime.auto_memory_max_tokens,
            )
            data = extract_json_object(raw)
            memories = data.get("memories", [])
            if not isinstance(memories, list):
                return

            # ── dedup & store ───────────────────────────────────────
            # Only query scope="user" for dedup so the target user's
            # own auto memories are never crowded out of the LIMIT 50
            # by other users' group-scoped entries.
            existing_results = self.store.search_memories(
                scope_key, user_id=str(user_id), query="", limit=50,
                scope="user",
            )
            existing_contents = [str(m.get("content", "")) for m in existing_results]

            stored_count = 0
            for item in memories:
                content = str(item).strip() if isinstance(item, str) else ""
                if not content or len(content) < 4:
                    continue
                if _is_duplicate_memory(content, existing_contents):
                    continue
                self.store.add_memory(
                    scope_key,
                    content,
                    scope="user",
                    user_id=user_id,
                    source="auto",
                    confidence=_AUTO_MEMORY_DEFAULT_CONFIDENCE,
                )
                existing_contents.append(content)
                stored_count += 1

            if stored_count:
                self.store.prune_memories(
                    scope_key,
                    min(
                        self.config.runtime.memory_max_items_per_group,
                        MAX_STORED_MEMORY_ITEMS,
                    ),
                )

            self._auto_memory_successes += 1
        except Exception:
            self._auto_memory_failures += 1
            logger.exception("auto_memory extraction failed for scope=%s", scope_key)
