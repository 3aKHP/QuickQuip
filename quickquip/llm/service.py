"""
LLM Service — framework-agnostic core.

Moved from ``plugins/llm_runtime.py`` so that the business logic lives
inside ``quickquip/`` with no NoneBot2 dependency.  The NoneBot2 plugin
layer now re-exports from here via ``plugins/llm_runtime.py``.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING

from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.common.json_utils import extract_json_object
from quickquip.common.sensitive_filter import (
    DEFAULT_BLOCK_REPLY,
    DEFAULT_OUTPUT_FALLBACK,
    SCRUB_PLACEHOLDER,
    get_filter as _get_sensitive_filter,
    log_hits as _log_sensitive_hits,
)
from quickquip.llm.config import LLMConfig, PersonaConfig, ProviderConfig, load_llm_config, load_personas_only
from quickquip.llm.defectify import build_defectify_prompt
from quickquip.llm.identity import IdentityIndex
from quickquip.llm.image_preprocessor import ImagePreprocessor
from quickquip.llm.mcp import MCPClientManager
from quickquip.llm.prompting import (
    build_messages,
    build_system_prompt,
    merge_image_urls,
)
from quickquip.llm.provider import (
    LLMProviderError,
    LLMRequest,
    build_provider_client,
    strip_leading_reasoning_content,
)
from quickquip.llm.service_parts.constants import (
    DEFAULT_PRIVATE_HISTORY_LIMIT,
    MAX_MEMORY_RETRIEVAL_ITEMS,
    MAX_STORED_MEMORY_ITEMS,
    MAX_TRIGGER_CONTEXT_MESSAGES,
)
from quickquip.llm.service_parts import HealthMixin, StateMixin, ToolMixin
from quickquip.llm.settings import ResolvedGroupSettings, resolve_group_settings
from quickquip.llm.store import LLMStore
from quickquip.llm.tool_registry import ToolRegistry
from quickquip.llm.tool_loop import run_tool_call_loop
from quickquip.llm.tools import (
    LLMConversationMessage,
    LLMToolSpec,
    ToolExecutionContext,
)
from quickquip.llm.vocab import VocabIndex
from quickquip.common.paths import (
    CONFIG_LLM_TOML,
    LLM_DB_PATH,
    LLM_IDENTITIES_YAML_PATH,
    LLM_VOCAB_YAML_PATH,
)
from quickquip.search.web_search import SearXNGSearchClient, format_search_response  # noqa: F401

if TYPE_CHECKING:
    from quickquip.chat.message_stats import GroupStatsTracker
    from quickquip.chat.rule_switch import GroupRuleSwitch
    from quickquip.common.recent_message_buffer import RecentMessageBuffer


CONFIG_PATH = CONFIG_LLM_TOML
DB_PATH = LLM_DB_PATH
VOCAB_PATH = LLM_VOCAB_YAML_PATH
IDENTITY_PATH = LLM_IDENTITIES_YAML_PATH
LLM_RULE_NAME = "llm_chat"
MAX_GROUP_STORED_CONVERSATION_MESSAGES = 20
MAX_PRIVATE_STORED_CONVERSATION_MESSAGES = 256
MAX_QUOTED_MESSAGE_CHARS = 1200
SEARCH_TOOL_NAME = "search_web"
TOOL_SEARCH_NAME = "tool_search"
TOOL_LIST_NAME = "tool_list"
SEARCH_TOOL_FAILSAFE_MAX_ROUNDS = 64
SEARCH_TOOL_FAILSAFE_MAX_CALLS_PER_ROUND = 64
PRIVATE_UNAVAILABLE_TOOLS = {"get_group_stats", "get_rule_status"}
DEFAULT_ALWAYS_LOADED_TOOLS = [
    TOOL_SEARCH_NAME,
    TOOL_LIST_NAME,
    "get_identity",
    "list_memories",
    SEARCH_TOOL_NAME,
]
DEFAULT_ENABLED_TOOLS = [
    TOOL_SEARCH_NAME,
    TOOL_LIST_NAME,
    "get_identity",
    "list_memories",
    SEARCH_TOOL_NAME,
    "get_group_stats",
    "get_rule_status",
    "search_recent_messages",
    "get_llm_status",
    "get_current_model",
    "get_health_status",
]
DEFECTIFY_RULE_NAME = "llm_defectify"
DEFECTIFY_MAX_OUTPUT_TOKENS = 512

# ── auto-memory extraction ──────────────────────────────────────────

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


logger = logging.getLogger(__name__)


class LLMService(ToolMixin, HealthMixin, StateMixin):
    def __init__(
        self,
        config_path: str | Path = CONFIG_PATH,
        db_path: str | Path = DB_PATH,
        vocab_path: str | Path = VOCAB_PATH,
        identity_path: str | Path = IDENTITY_PATH,
        image_preprocessor: ImagePreprocessor | None = None,
    ):
        self.config_path = Path(config_path)
        self.vocab_path = Path(vocab_path)
        self.identity_path = Path(identity_path)
        self.tool_registry = ToolRegistry()
        self.mcp_manager = MCPClientManager()
        self.image_preprocessor = image_preprocessor
        self.stats_tracker: "GroupStatsTracker | None" = None
        self.rule_switch: "GroupRuleSwitch | None" = None
        self.recent_message_buffer: "RecentMessageBuffer | None" = None
        self._mcp_tool_names: set[str] = set()
        self._mcp_dirty = True
        self._mcp_lock = asyncio.Lock()
        self._mcp_startup_task: asyncio.Task[None] | None = None
        self._session_presets: dict[str, str] = {}
        self._auto_memory_turns: dict[str, int] = {}
        self._auto_memory_successes = 0
        self._auto_memory_failures = 0
        self._init_error: str | None = None

        self._register_builtin_tools()
        self.config = load_llm_config(self.config_path)

        try:
            self.store = LLMStore(db_path)
        except Exception as exc:
            logger.exception("LLMStore 初始化失败")
            self.store = None  # type: ignore[assignment]
            self._init_error = f"数据库初始化失败：{exc}"

        if self.image_preprocessor is None:
            try:
                self.rebuild_image_preprocessor()
            except Exception:
                logger.exception("image_preprocessor 初始化失败")

        try:
            self.vocab = VocabIndex.from_file(self.vocab_path)
        except Exception as exc:
            logger.exception("vocab 加载失败")
            self.vocab = VocabIndex()
            if not self._init_error:
                self._init_error = f"词表加载失败：{exc}"

        try:
            self.identities = IdentityIndex.from_file(self.identity_path)
        except Exception as exc:
            logger.exception("identities 加载失败")
            self.identities = IdentityIndex()
            if not self._init_error:
                self._init_error = f"身份资料加载失败：{exc}"

        self._group_vocabs: dict[str, VocabIndex] = {}
        self._group_identities: dict[str, IdentityIndex] = {}

    def _resolve_vocab(self, group_id: str) -> VocabIndex:
        if not group_id:
            return self.vocab
        cache_key = str(group_id)
        cached = self._group_vocabs.get(cache_key)
        if cached is not None:
            return cached
        group_path = self.vocab_path.parent / cache_key / "vocab.yaml"
        if group_path.exists():
            group_vocab = VocabIndex.from_file(group_path)
            merged = self.vocab.merge(group_vocab)
        else:
            merged = self.vocab
        self._group_vocabs[cache_key] = merged
        return merged

    def _resolve_identities(self, group_id: str) -> IdentityIndex:
        if not group_id:
            return self.identities
        cache_key = str(group_id)
        cached = self._group_identities.get(cache_key)
        if cached is not None:
            return cached
        group_path = self.identity_path.parent / cache_key / "identities.yaml"
        if group_path.exists():
            group_identities = IdentityIndex.from_file(group_path)
            merged = self.identities.merge(group_identities)
        else:
            merged = self.identities
        self._group_identities[cache_key] = merged
        return merged


    def reload_config(self) -> LLMConfig:
        self.config = load_llm_config(self.config_path)
        self.rebuild_image_preprocessor()
        self.vocab = VocabIndex.from_file(self.vocab_path)
        self.identities = IdentityIndex.from_file(self.identity_path)
        self._group_vocabs.clear()
        self._group_identities.clear()
        self._mcp_dirty = True
        return self.config

    def reload_personas(self) -> tuple[int, str | None]:
        """Reload only the personas section (``[[personas]]`` + ``config/personas/``).

        Does **not** touch providers / MCP / runtime — those stay as loaded at
        startup, since reloading them requires restarting provider clients and
        reinitialising MCP sessions. Returns ``(count, error_message)``; on
        error or an empty result, the previous ``self.config.personas`` is kept.
        """
        try:
            new_personas = load_personas_only(self.config_path)
        except Exception as exc:
            return 0, str(exc)
        if not new_personas:
            return 0, "配置中没有可用的人格"
        self.config.personas = new_personas
        if self.config.runtime.default_persona not in new_personas:
            self.config.runtime.default_persona = next(iter(new_personas))
        return len(new_personas), None

    def build_chat_scope_key(self, chat_id: int | str, chat_type: str = "group") -> str:
        if chat_type == "private":
            return f"private:{chat_id}"
        return str(chat_id)

    def _scope_label(self, chat_type: str) -> str:
        return "私聊" if chat_type == "private" else "群聊"

    def _scope_subject(self, chat_type: str) -> str:
        return "当前私聊" if chat_type == "private" else "本群"

    def _memory_label(self, chat_type: str) -> str:
        return "当前私聊记忆" if chat_type == "private" else "当前群记忆"

    def _model_label(self, chat_type: str) -> str:
        return "当前私聊模型配置" if chat_type == "private" else "当前群模型配置"

    def _default_history_limit(self, chat_type: str) -> int:
        if chat_type == "private":
            return max(self.config.runtime.history_limit, DEFAULT_PRIVATE_HISTORY_LIMIT)
        return self.config.runtime.history_limit

    def get_default_history_limit(self, chat_type: str = "group") -> int:
        return self._default_history_limit(chat_type)

    def _max_stored_conversation_messages(self, chat_type: str) -> int:
        if chat_type == "private":
            return MAX_PRIVATE_STORED_CONVERSATION_MESSAGES
        return MAX_GROUP_STORED_CONVERSATION_MESSAGES

    def _history_retention_limit(self, chat_type: str) -> int:
        if chat_type == "private":
            return max(self.config.runtime.history_max_messages_per_group, MAX_PRIVATE_STORED_CONVERSATION_MESSAGES)
        return min(self.config.runtime.history_max_messages_per_group, MAX_GROUP_STORED_CONVERSATION_MESSAGES)

    def _context_scope_key(self, context: ToolExecutionContext) -> str:
        if context.chat_scope:
            return context.chat_scope
        return self.build_chat_scope_key(context.group_id, context.chat_type)

    def get_chat_settings(self, chat_id: int | str, chat_type: str = "group") -> ResolvedGroupSettings:
        scope_key = self.build_chat_scope_key(chat_id, chat_type)
        overrides = self.store.get_group_settings(scope_key)
        settings = resolve_group_settings(self.store, self.config, scope_key)
        if chat_type == "private":
            settings = replace(
                settings,
                enabled=False if overrides.enabled is None else settings.enabled,
                allow_at=False,
            )
        return settings

    def get_group_settings(self, group_id: int | str) -> ResolvedGroupSettings:
        return self.get_chat_settings(group_id, chat_type="group")

    def _update_chat_settings(self, chat_id: int | str, chat_type: str = "group", **fields: object) -> None:
        self.store.update_group_settings(self.build_chat_scope_key(chat_id, chat_type), **fields)

    def _get_enabled_tool_names(self, chat_type: str = "group") -> list[str]:
        names = self.config.tools.enabled or [*DEFAULT_ENABLED_TOOLS, *sorted(self._mcp_tool_names)]
        if chat_type == "private":
            names = [name for name in names if name not in PRIVATE_UNAVAILABLE_TOOLS]
        return [name for name in names if self.tool_registry.has_tool(name)]

    def _get_always_loaded_tool_names(self, chat_type: str = "group") -> list[str]:
        configured = self.config.tools.always_loaded or DEFAULT_ALWAYS_LOADED_TOOLS
        enabled = set(self._get_enabled_tool_names(chat_type=chat_type))
        names = [name for name in configured if name in enabled and self.tool_registry.has_tool(name)]
        if self._is_tool_discovery_enabled(chat_type) and TOOL_SEARCH_NAME in enabled and TOOL_SEARCH_NAME not in names:
            names.insert(0, TOOL_SEARCH_NAME)
        return names

    def _is_tool_discovery_enabled(self, chat_type: str = "group") -> bool:
        mode = self.config.tools.discovery_mode
        if mode == "off":
            return False
        if TOOL_SEARCH_NAME not in self._get_enabled_tool_names(chat_type=chat_type):
            return False
        enabled_count = len(self._get_enabled_tool_names(chat_type=chat_type))
        if mode == "on":
            configured = self.config.tools.always_loaded or DEFAULT_ALWAYS_LOADED_TOOLS
            always_count = len([
                name for name in configured
                if name in self._get_enabled_tool_names(chat_type=chat_type)
                and self.tool_registry.has_tool(name)
            ])
            return enabled_count > always_count
        configured = self.config.tools.always_loaded or DEFAULT_ALWAYS_LOADED_TOOLS
        always_names = {
            name for name in configured
            if name in self._get_enabled_tool_names(chat_type=chat_type)
            and self.tool_registry.has_tool(name)
        }
        deferred_count = len([
            name for name in self._get_enabled_tool_names(chat_type=chat_type)
            if name not in always_names
        ])
        return deferred_count > self.config.tools.discovery_min_tools

    def _get_enabled_tool_specs(self, chat_type: str = "group") -> list[LLMToolSpec]:
        if self._is_tool_discovery_enabled(chat_type):
            return self.tool_registry.get_specs(self._get_always_loaded_tool_names(chat_type=chat_type))
        return self.tool_registry.list_specs(self._get_enabled_tool_names(chat_type=chat_type))

    def _get_deferred_tool_categories(self, chat_type: str = "group") -> list[str]:
        if not self._is_tool_discovery_enabled(chat_type):
            return []
        loaded = set(self._get_always_loaded_tool_names(chat_type=chat_type))
        categories: list[str] = []
        for entry in self.tool_registry.list_manifest(self._get_enabled_tool_names(chat_type=chat_type)):
            if entry.name in loaded:
                continue
            category = entry.category or entry.source
            if category and category not in categories:
                categories.append(category)
        return categories

    def _build_system_prompt(
        self,
        persona: PersonaConfig,
        group_id: int | str,
        chat_type: str,
        user_id: int | str,
        sender_name: str,
        prompt: str,
        memories: list[dict[str, object]],
        tool_specs: list[LLMToolSpec],
        participants: list[dict[str, str]] | None = None,
        provider_style_overrides: str = "",
        session_preset: str = "",
    ) -> str:
        return build_system_prompt(
            persona=persona,
            group_id=group_id,
            user_id=user_id,
            sender_name=sender_name,
            prompt=prompt,
            memories=memories,
            tool_specs=tool_specs,
            identities=self._resolve_identities(str(group_id)),
            vocab=self._resolve_vocab(str(group_id)),
            beijing_timezone=BEIJING_TIMEZONE,
            search_tool_name=SEARCH_TOOL_NAME,
            auto_search_enabled=self.config.auto_search.enabled,
            tool_discovery_enabled=self._is_tool_discovery_enabled(chat_type),
            tool_search_name=TOOL_SEARCH_NAME,
            tool_list_name=TOOL_LIST_NAME,
            deferred_tool_categories=self._get_deferred_tool_categories(chat_type),
            chat_type=chat_type,
            participants=participants,
            provider_style_overrides=provider_style_overrides,
            session_preset=session_preset,
        )

    async def quick_judge(self, prompt: str, max_tokens: int = 64) -> str:
        """
        用于 context_rules 的极速判定调用。
        不走群配置、不注入记忆、不启用工具，只发单条 system+user。
        """
        provider_id = self.config.runtime.default_provider
        if not provider_id or provider_id not in self.config.providers:
            provider_id = next(iter(self.config.providers), None)
        if not provider_id:
            return '{"trigger": false}'

        provider = self.config.providers[provider_id]
        judge_provider = replace(provider, stream_enabled=False)

        request = LLMRequest(
            model=judge_provider.default_model,
            system_prompt="你是一个仅输出 JSON 的判定器。",
            messages=[
                LLMConversationMessage(role="user", content=prompt),
            ],
            temperature=0.0,
            max_output_tokens=max_tokens,
            thinking_budget=None,
            tools=[],
            allow_tool_calls=False,
            tool_choice="none",
        )
        client = build_provider_client(judge_provider)
        response = await client.complete(request)
        return strip_leading_reasoning_content(response.text or "")

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
            if len(self._auto_memory_turns) >= _AUTO_MEMORY_TURN_CACHE_MAX:
                self._auto_memory_turns.clear()
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

    def _merge_image_urls(self, *collections: list[str]) -> list[str]:
        return merge_image_urls(*collections)


    def _build_messages(
        self,
        *,
        prompt: str,
        image_urls: list[str],
        history: list[dict[str, str]],
        recent_messages: list[dict[str, str]] | None,
        chat_type: str = "group",
        group_id: str = "",
        current_sender_name: str = "",
        current_user_id: str = "",
        quoted_text: str = "",
        quoted_sender_name: str = "",
        quoted_user_id: str = "",
        quoted_image_urls: list[str] | None = None,
        quoted_is_bot_self: bool = False,
        forward_text: str = "",
        forward_image_urls: list[str] | None = None,
        image_descriptions: list[object] | None = None,
    ) -> list[LLMConversationMessage]:
        return build_messages(
            prompt=prompt,
            image_urls=image_urls,
            history=history,
            recent_messages=recent_messages,
            max_trigger_context_messages=MAX_TRIGGER_CONTEXT_MESSAGES,
            chat_type=chat_type,
            identities=self._resolve_identities(group_id),
            current_sender_name=current_sender_name,
            current_user_id=current_user_id,
            quoted_text=quoted_text,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
            quoted_image_urls=quoted_image_urls,
            quoted_is_bot_self=quoted_is_bot_self,
            forward_text=forward_text,
            forward_image_urls=forward_image_urls,
            image_descriptions=image_descriptions,
        )

    async def generate_defectify_reply(
        self,
        *,
        chat_id: int | str,
        chat_type: str,
        user_id: int | str,
        sender_name: str,
        prompt: str,
        image_urls: list[str] | None = None,
        quoted_text: str = "",
        quoted_image_urls: list[str] | None = None,
        quoted_sender_name: str = "",
        quoted_user_id: str = "",
        quoted_is_bot_self: bool = False,
    ) -> dict[str, str]:
        normalized_prompt = prompt.strip()
        normalized_image_urls = [url.strip() for url in (image_urls or []) if url.strip()]
        normalized_quoted_text = quoted_text.strip()
        normalized_quoted_image_urls = [url.strip() for url in (quoted_image_urls or []) if url.strip()]
        if not normalized_prompt and not normalized_image_urls and not normalized_quoted_text and not normalized_quoted_image_urls:
            return {
                "reply": "用法：/defectify <文字>，也可以在命令里附图，或引用一条消息/图片后直接发送 /defectify。",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": DEFECTIFY_RULE_NAME,
            }

        if self.config.load_error:
            return {
                "reply": f"LLM 配置不可用：{self.config.load_error}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": DEFECTIFY_RULE_NAME,
            }

        settings = self.get_chat_settings(chat_id, chat_type=chat_type)
        provider = self.config.providers.get(settings.provider_id)
        if provider is None:
            return {
                "reply": f"当前 provider 不存在：{settings.provider_id}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": DEFECTIFY_RULE_NAME,
            }

        prompt_pack = build_defectify_prompt(
            prompt=normalized_prompt,
            image_urls=normalized_image_urls,
            quoted_text=normalized_quoted_text,
            quoted_image_urls=normalized_quoted_image_urls,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
        )
        effective_image_urls = self._merge_image_urls(normalized_image_urls, normalized_quoted_image_urls)
        defectify_provider = replace(provider, stream_enabled=False)
        request = LLMRequest(
            model=settings.model or provider.default_model,
            system_prompt=prompt_pack.system_prompt,
            messages=[
                LLMConversationMessage(
                    role="user",
                    content=prompt_pack.user_prompt,
                    image_urls=effective_image_urls,
                )
            ],
            temperature=0.9,
            max_output_tokens=min(provider.max_output_tokens, DEFECTIFY_MAX_OUTPUT_TOKENS),
            thinking_budget=None,
            tools=[],
            allow_tool_calls=False,
            tool_choice="none",
        )

        try:
            response = await build_provider_client(defectify_provider).complete(request)
        except LLMProviderError as exc:
            return {
                "reply": f"LLM 调用失败：{exc}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": DEFECTIFY_RULE_NAME,
            }
        except Exception as exc:
            return {
                "reply": f"LLM 调用异常：{exc}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": DEFECTIFY_RULE_NAME,
            }

        text = strip_leading_reasoning_content(response.text).strip()
        if not text:
            return {
                "reply": "模型没有返回可显示的文本。",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": DEFECTIFY_RULE_NAME,
            }
        return {
            "reply": text,
            "rate_limit_key": LLM_RULE_NAME,
            "rule_name": DEFECTIFY_RULE_NAME,
        }

    def _collect_known_participants(
        self,
        *,
        user_id: int | str,
        sender_name: str,
        history: list[dict[str, str]],
        recent_messages: list[dict[str, str]] | None = None,
        quoted_sender_name: str = "",
        quoted_user_id: str = "",
        group_id: str = "",
    ) -> list[dict[str, str]]:
        participants: list[dict[str, str]] = []
        seen_user_ids: set[str] = set()
        identities = self._resolve_identities(group_id)

        def _push(raw_user_id: int | str | None, raw_sender_name: str = "", raw_canonical_name: str = "") -> None:
            user_key = str(raw_user_id or "").strip()
            sender_value = raw_sender_name.strip()
            canonical_value = raw_canonical_name.strip()
            if not user_key and not sender_value:
                return
            dedupe_key = user_key or f"name:{sender_value}"
            if dedupe_key in seen_user_ids:
                return
            seen_user_ids.add(dedupe_key)
            if user_key:
                identity = identities.resolve_user(user_key, sender_value)
                if identity.is_registered:
                    canonical_value = identity.canonical_name or canonical_value
                    sender_value = sender_value or identity.sender_name or user_key
            participants.append(
                {
                    "user_id": user_key,
                    "sender_name": sender_value or user_key,
                    "canonical_name": canonical_value,
                }
            )

        _push(user_id, sender_name)
        if quoted_sender_name or quoted_user_id:
            _push(quoted_user_id, quoted_sender_name)
        for item in recent_messages or []:
            _push(item.get("user_id", ""), item.get("sender_name", ""), item.get("canonical_name", ""))
        for item in history:
            if item.get("role") != "user":
                continue
            _push(item.get("user_id", ""), item.get("sender_name", ""), item.get("canonical_name", ""))
        return participants

    async def _run_tool_call_loop(
        self,
        *,
        provider: ProviderConfig,
        request: LLMRequest,
        context: ToolExecutionContext,
    ):
        return await run_tool_call_loop(
            provider=provider,
            request=request,
            context=context,
            build_provider_client=build_provider_client,
            tool_registry=self.tool_registry,
            runtime_config=self.config.runtime,
            logger=logger,
            search_tool_name=SEARCH_TOOL_NAME,
            search_failsafe_max_rounds=SEARCH_TOOL_FAILSAFE_MAX_ROUNDS,
            search_failsafe_max_calls_per_round=SEARCH_TOOL_FAILSAFE_MAX_CALLS_PER_ROUND,
            search_max_calls_per_round=self.config.auto_search.search_max_calls_per_round,
            tool_discovery_enabled=self._is_tool_discovery_enabled(context.chat_type),
            tool_search_name=TOOL_SEARCH_NAME,
            tool_list_name=TOOL_LIST_NAME,
            enabled_tool_names=self._get_enabled_tool_names(chat_type=context.chat_type),
            initial_tool_names=[spec.name for spec in request.tools],
            tool_discovery_search_limit=self.config.tools.discovery_search_limit,
            tool_discovery_max_loaded_tools=self.config.tools.discovery_max_loaded_tools,
        )

    async def _generate_reply_for_scope(
        self,
        *,
        chat_id: int | str,
        chat_type: str,
        user_id: int | str,
        sender_name: str,
        prompt: str,
        image_urls: list[str] | None = None,
        recent_messages: list[dict[str, str]] | None = None,
        quoted_text: str = "",
        quoted_image_urls: list[str] | None = None,
        quoted_sender_name: str = "",
        quoted_user_id: str = "",
        quoted_is_bot_self: bool = False,
        forward_text: str = "",
        forward_image_urls: list[str] | None = None,
        voice_text: str = "",
        message_id: str | None = None,
    ) -> dict[str, str]:
        prompt = prompt.strip()
        normalized_image_urls = [url for url in (image_urls or []) if url.strip()]
        normalized_quoted_text = quoted_text.strip()
        normalized_quoted_image_urls = [url for url in (quoted_image_urls or []) if url.strip()]
        normalized_forward_text = forward_text.strip()
        normalized_forward_image_urls = [url for url in (forward_image_urls or []) if url.strip()]
        normalized_voice_text = voice_text.strip()
        if normalized_voice_text:
            prompt = "\n".join(item for item in [prompt, normalized_voice_text] if item).strip()
        request_image_urls = list(normalized_image_urls)
        request_quoted_image_urls = list(normalized_quoted_image_urls)
        request_forward_image_urls = list(normalized_forward_image_urls)
        if not prompt and normalized_image_urls and not normalized_quoted_text and not normalized_quoted_image_urls and not normalized_forward_text and not normalized_forward_image_urls:
            prompt = "请描述这张图片，并优先回答群友最可能想知道的内容。"

        if not prompt and not normalized_quoted_text and not normalized_image_urls and not normalized_quoted_image_urls and not normalized_forward_text and not normalized_forward_image_urls:
            return {
                "reply": self.config.triggers.empty_prompt_reply,
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        scope_key = self.build_chat_scope_key(chat_id, chat_type)
        sensitive = _get_sensitive_filter()
        if sensitive.is_loaded:
            input_blob = "\n".join(
                part for part in (
                    prompt,
                    normalized_quoted_text,
                    normalized_forward_text,
                ) if part
            )
            input_scan = sensitive.scan(input_blob)
            if input_scan.hits:
                _log_sensitive_hits("input", scope_key, input_scan)
            if input_scan.blocked:
                return {
                    "reply": DEFAULT_BLOCK_REPLY,
                    "rate_limit_key": LLM_RULE_NAME,
                    "rule_name": LLM_RULE_NAME,
                }

        if self.config.load_error:
            return {
                "reply": f"LLM 配置不可用：{self.config.load_error}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        settings = self.get_chat_settings(chat_id, chat_type=chat_type)
        if not settings.enabled:
            return {
                "reply": f"{self._scope_subject(chat_type)} LLM 已关闭。",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        provider = self.config.providers.get(settings.provider_id)
        if provider is None:
            return {
                "reply": f"当前 provider 不存在：{settings.provider_id}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        persona = self.config.personas.get(settings.persona_id)
        if persona is None:
            return {
                "reply": f"当前 persona 不存在：{settings.persona_id}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        trimmed_prompt = prompt[: self.config.runtime.max_prompt_chars]
        quoted_prompt = normalized_quoted_text[:MAX_QUOTED_MESSAGE_CHARS]
        analysis_prompt = "\n".join(
            item for item in [trimmed_prompt, quoted_prompt] if item
        )[: self.config.runtime.max_prompt_chars]

        # ── image preprocessing & non-VLM stripping ──────────────────
        current_model = settings.model or provider.default_model
        is_non_vision = current_model in provider.non_vision_models

        effective_image_urls = merge_image_urls(request_image_urls, request_quoted_image_urls, request_forward_image_urls)

        if effective_image_urls:
            sources: list[str] = []
            if normalized_image_urls:
                sources.append(f"直接={len(normalized_image_urls)}")
            if normalized_quoted_image_urls:
                sources.append(f"引用={len(normalized_quoted_image_urls)}")
            if normalized_forward_image_urls:
                sources.append(f"转发={len(normalized_forward_image_urls)}")
            logger.info(
                "group=%s model=%s non_vision=%s images=%d (%s)",
                chat_id, current_model, is_non_vision,
                len(effective_image_urls), ", ".join(sources),
            )

        image_descriptions = []
        ok_count = 0
        if self.image_preprocessor is not None and effective_image_urls:
            image_descriptions = await self.image_preprocessor.describe_images(effective_image_urls)
            ok_count = sum(1 for d in image_descriptions if d.success)
            fail = len(image_descriptions) - ok_count
            if fail:
                logger.warning(
                    "group=%s preprocessor: %d ok, %d failed (%s)",
                    chat_id, ok_count, fail,
                    ", ".join(d.source_url for d in image_descriptions if not d.success),
                )
            else:
                logger.info("group=%s preprocessor: all %d images described", chat_id, ok_count)

        if is_non_vision and effective_image_urls:
            stripped_count = len(effective_image_urls)
            extra = f" ({ok_count} described as text)" if ok_count else " (no preprocessing)"
            logger.info(
                "group=%s non-VLM strip: removed %d images from provider request%s",
                chat_id, stripped_count, extra,
            )
            effective_image_urls = []
            request_image_urls = []
            request_quoted_image_urls = []
            request_forward_image_urls = []

        # ── end image preprocessing ─────────────────────────────────
        default_history_limit = self._default_history_limit(chat_type)
        history = self.store.list_recent_conversation_messages(
            scope_key,
            min(
                settings.history_limit if settings.history_limit is not None else default_history_limit,
                self._max_stored_conversation_messages(chat_type),
            ),
        )
        if sensitive.is_loaded and history:
            # Re-scan history with the *current* word list — entries written
            # under an older list may now contain blocked content. Scrubbing
            # here keeps the next request's context clean without rewriting
            # the on-disk store.
            history_blocked = 0
            for item in history:
                for field_name in ("content", "raw_content"):
                    original = item.get(field_name)
                    if not original:
                        continue
                    scrubbed = sensitive.scrub(str(original), SCRUB_PLACEHOLDER)
                    if scrubbed != original:
                        item[field_name] = scrubbed
                        history_blocked += 1
            if history_blocked:
                logger.info(
                    "sensitive_filter[history] scrubbed scope=%s fields=%d",
                    scope_key, history_blocked,
                )
        participants = self._collect_known_participants(
            user_id=user_id,
            sender_name=sender_name,
            history=history,
            recent_messages=recent_messages,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
            group_id=str(chat_id),
        )
        if self.config.mcp.enabled:
            await self.ensure_mcp_ready()
        memories: list[dict[str, object]] = []
        if settings.memory_enabled:
            memories = self.store.search_memories(
                scope_key,
                user_id=user_id,
                query=analysis_prompt or trimmed_prompt,
                limit=min(self.config.runtime.memory_limit, MAX_MEMORY_RETRIEVAL_ITEMS),
            )

        tool_specs = self._get_enabled_tool_specs(chat_type=chat_type) if self.config.runtime.tool_calling_enabled else []
        session_preset = self.get_session_preset(scope_key) if chat_type == "private" else ""
        system_prompt = self._build_system_prompt(
            persona,
            chat_id,
            chat_type,
            user_id,
            sender_name,
            analysis_prompt or trimmed_prompt,
            memories,
            tool_specs,
            participants=participants,
            provider_style_overrides=provider.style_overrides,
            session_preset=session_preset,
        )
        messages = self._build_messages(
            prompt=trimmed_prompt,
            image_urls=effective_image_urls,
            history=history,
            recent_messages=recent_messages,
            chat_type=chat_type,
            group_id=str(chat_id),
            current_sender_name=sender_name,
            current_user_id=str(user_id),
            quoted_text=quoted_prompt,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
            quoted_image_urls=request_quoted_image_urls,
            quoted_is_bot_self=quoted_is_bot_self,
            forward_text=normalized_forward_text,
            forward_image_urls=request_forward_image_urls,
            image_descriptions=image_descriptions or None,
        )
        request = LLMRequest(
            model=settings.model or provider.default_model,
            system_prompt=system_prompt,
            messages=messages,
            temperature=provider.temperature,
            max_output_tokens=provider.max_output_tokens,
            tools=tool_specs,
            allow_tool_calls=bool(tool_specs),
            tool_choice="auto",
        )
        tool_context = ToolExecutionContext(
            group_id=chat_id,
            user_id=user_id,
            sender_name=sender_name,
            provider_id=provider.id,
            model=request.model,
            chat_scope=scope_key,
            chat_type=chat_type,
        )

        try:
            response = await self._run_tool_call_loop(
                provider=provider,
                request=request,
                context=tool_context,
            )
        except LLMProviderError as exc:
            return {
                "reply": f"LLM 调用失败：{exc}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }
        except Exception as exc:
            return {
                "reply": f"LLM 调用异常：{exc}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        text = strip_leading_reasoning_content(response.text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text:
            text = "模型没有返回可显示的文本。"

        if sensitive.is_loaded:
            output_scan = sensitive.scan(text)
            if output_scan.hits:
                _log_sensitive_hits("output", scope_key, output_scan)
            if output_scan.blocked:
                # Don't write the blocked output to history — that would
                # poison the next turn's context. Substitute the fallback
                # for both the user-visible reply and what we persist.
                text = DEFAULT_OUTPUT_FALLBACK

        current_identity = self._resolve_identities(str(chat_id)).resolve_user(user_id, sender_name)
        raw_turn_parts: list[str] = []
        if normalized_quoted_text or normalized_quoted_image_urls:
            q_text = normalized_quoted_text or f"[图片 {len(normalized_quoted_image_urls)} 张]"
            q_suffix = f" [附图 {len(normalized_quoted_image_urls)} 张]" if normalized_quoted_image_urls else ""
            raw_turn_parts.append(f"[引用] {q_text}{q_suffix}")
        if normalized_forward_text or normalized_forward_image_urls:
            fw_text = normalized_forward_text or "[合并转发消息]"
            fw_suffix = f" [附图 {len(normalized_forward_image_urls)} 张]" if normalized_forward_image_urls else ""
            raw_turn_parts.append(fw_text + fw_suffix)
        raw_turn_parts.append(trimmed_prompt)
        raw_turn = "\n".join(raw_turn_parts)
        self.store.append_conversation_message(
            scope_key,
            user_id,
            "user",
            trimmed_prompt,
            sender_name=sender_name,
            canonical_name=current_identity.canonical_name,
            message_id=str(message_id) if message_id else None,
            raw_content=raw_turn,
        )
        self.store.append_conversation_message(scope_key, None, "assistant", text)
        self.store.prune_conversation_messages(
            scope_key,
            self._history_retention_limit(chat_type),
        )

        if settings.auto_memory_enabled and settings.memory_enabled:
            asyncio.create_task(
                self._extract_auto_memory(
                    scope_key=scope_key,
                    user_id=user_id,
                    sender_name=sender_name,
                    canonical_name=current_identity.canonical_name,
                    user_text=trimmed_prompt,
                    assistant_text=text,
                )
            )

        return {
            "reply": text,
            "rate_limit_key": LLM_RULE_NAME,
            "rule_name": LLM_RULE_NAME,
        }

    async def generate_reply(
        self,
        *,
        group_id: int | str,
        user_id: int | str,
        sender_name: str,
        prompt: str,
        image_urls: list[str] | None = None,
        recent_messages: list[dict[str, str]] | None = None,
        quoted_text: str = "",
        quoted_image_urls: list[str] | None = None,
        quoted_sender_name: str = "",
        quoted_user_id: str = "",
        quoted_is_bot_self: bool = False,
        forward_text: str = "",
        forward_image_urls: list[str] | None = None,
        voice_text: str = "",
        message_id: str | None = None,
    ) -> dict[str, str]:
        return await self._generate_reply_for_scope(
            chat_id=group_id,
            chat_type="group",
            user_id=user_id,
            sender_name=sender_name,
            prompt=prompt,
            image_urls=image_urls,
            recent_messages=recent_messages,
            quoted_text=quoted_text,
            quoted_image_urls=quoted_image_urls,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
            quoted_is_bot_self=quoted_is_bot_self,
            forward_text=forward_text,
            forward_image_urls=forward_image_urls,
            voice_text=voice_text,
            message_id=message_id,
        )

    async def generate_private_reply(
        self,
        *,
        user_id: int | str,
        sender_name: str,
        prompt: str,
        image_urls: list[str] | None = None,
        recent_messages: list[dict[str, str]] | None = None,
        quoted_text: str = "",
        quoted_image_urls: list[str] | None = None,
        quoted_sender_name: str = "",
        quoted_user_id: str = "",
        quoted_is_bot_self: bool = False,
        forward_text: str = "",
        forward_image_urls: list[str] | None = None,
        voice_text: str = "",
        message_id: str | None = None,
    ) -> dict[str, str]:
        return await self._generate_reply_for_scope(
            chat_id=user_id,
            chat_type="private",
            user_id=user_id,
            sender_name=sender_name,
            prompt=prompt,
            image_urls=image_urls,
            recent_messages=recent_messages,
            quoted_text=quoted_text,
            quoted_image_urls=quoted_image_urls,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
            quoted_is_bot_self=quoted_is_bot_self,
            forward_text=forward_text,
            forward_image_urls=forward_image_urls,
            voice_text=voice_text,
            message_id=message_id,
        )


_llm_service: LLMService | None = None
_init_attempted: bool = False


def get_llm_service() -> LLMService:
    """Return the singleton LLMService, lazily initialising it on first call.

    Unlike the old module-level ``llm_service = LLMService()`` pattern, this
    function does not run any initialisation at import time.  If
    ``LLMService.__init__`` fails, the exception is logged and a degraded
    service object (with ``_init_error`` set) is returned rather than
    crashing the process.
    """
    global _llm_service, _init_attempted
    if not _init_attempted:
        _init_attempted = True
        try:
            _llm_service = LLMService()
        except Exception as exc:
            logger.critical("LLMService 初始化失败，创建降级实例：%s", exc)
            _llm_service = LLMService.__new__(LLMService)
            _llm_service._init_error = str(exc)  # type: ignore[attr-defined]
    return _llm_service  # type: ignore[return-value]
