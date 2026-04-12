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
from quickquip.llm.config import LLMConfig, PersonaConfig, ProviderConfig, load_llm_config
from quickquip.llm.defectify import build_defectify_prompt
from quickquip.llm.identity import IdentityIndex
from quickquip.llm.mcp import MCPClientManager, MCPServerStatus
from quickquip.llm.prompting import (
    build_messages,
    build_system_prompt,
    build_user_message_content,
    merge_image_urls,
)
from quickquip.llm.provider import (
    LLMProviderError,
    LLMRequest,
    build_provider_client,
    strip_leading_reasoning_content,
)
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
from quickquip.search.web_search import build_search_client, format_search_response, get_search_backend_name

if TYPE_CHECKING:
    from quickquip.chat.message_stats import GroupStatsTracker
    from quickquip.chat.rule_switch import GroupRuleSwitch
    from quickquip.common.recent_message_buffer import RecentMessageBuffer


CONFIG_PATH = Path("config/llm.toml")
DB_PATH = Path("data/llm.db")
VOCAB_PATH = Path("dev/llm_about/vocab.yaml")
IDENTITY_PATH = Path("dev/llm_about/identities.yaml")
LLM_RULE_NAME = "llm_chat"
MAX_TRIGGER_CONTEXT_MESSAGES = 20
MAX_GROUP_STORED_CONVERSATION_MESSAGES = 20
MAX_PRIVATE_STORED_CONVERSATION_MESSAGES = 256
MAX_MEMORY_RETRIEVAL_ITEMS = 8
MAX_STORED_MEMORY_ITEMS = 200
MAX_QUOTED_MESSAGE_CHARS = 1200
SEARCH_TOOL_NAME = "search_web"
SEARCH_TOOL_FAILSAFE_MAX_ROUNDS = 64
SEARCH_TOOL_FAILSAFE_MAX_CALLS_PER_ROUND = 64
DEFAULT_PRIVATE_HISTORY_LIMIT = 256
PRIVATE_UNAVAILABLE_TOOLS = {"get_group_stats", "get_rule_status"}
DEFAULT_ENABLED_TOOLS = [
    "get_identity",
    "list_memories",
    SEARCH_TOOL_NAME,
    "get_group_stats",
    "get_rule_status",
    "search_recent_messages",
    "get_llm_status",
    "get_current_model",
]
DEFECTIFY_RULE_NAME = "llm_defectify"
DEFECTIFY_MAX_OUTPUT_TOKENS = 512

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(
        self,
        config_path: str | Path = CONFIG_PATH,
        db_path: str | Path = DB_PATH,
        vocab_path: str | Path = VOCAB_PATH,
        identity_path: str | Path = IDENTITY_PATH,
    ):
        self.config_path = Path(config_path)
        self.store = LLMStore(db_path)
        self.vocab_path = Path(vocab_path)
        self.identity_path = Path(identity_path)
        self.tool_registry = ToolRegistry()
        self.mcp_manager = MCPClientManager()
        self.stats_tracker: "GroupStatsTracker | None" = None
        self.rule_switch: "GroupRuleSwitch | None" = None
        self.recent_message_buffer: "RecentMessageBuffer | None" = None
        self._mcp_tool_names: set[str] = set()
        self._mcp_dirty = True
        self._mcp_lock = asyncio.Lock()
        self._mcp_startup_task: asyncio.Task[None] | None = None
        self._session_presets: dict[str, str] = {}
        self._register_builtin_tools()
        self.config = load_llm_config(self.config_path)
        self.vocab = VocabIndex.from_file(self.vocab_path)
        self.identities = IdentityIndex.from_file(self.identity_path)

    def _register_builtin_tools(self) -> None:
        self.tool_registry.register(
            LLMToolSpec(
                name="get_identity",
                description="按标准名、别名或 QQ 号查询当前群资料库中的人物身份信息。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                },
            ),
            self._tool_get_identity,
        )
        self.tool_registry.register(
            LLMToolSpec(
                name="list_memories",
                description="查看当前群已存的长期记忆，可选按关键词过滤。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string"},
                    },
                },
            ),
            self._tool_list_memories,
        )
        self.tool_registry.register(
            LLMToolSpec(
                name="search_web",
                description="使用当前搜索后端对最新信息进行联网搜索。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "topic": {"type": "string", "enum": ["general", "news", "finance"]},
                    },
                    "required": ["query"],
                },
            ),
            self._tool_search_web,
        )
        self.tool_registry.register(
            LLMToolSpec(
                name="get_group_stats",
                description="查看当前群消息统计，包括总消息数、活跃用户和规则触发情况。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "top_n": {"type": "integer"},
                    },
                },
            ),
            self._tool_get_group_stats,
        )
        self.tool_registry.register(
            LLMToolSpec(
                name="get_rule_status",
                description="查看当前群规则开关状态，可查询某条规则是否开启，或列出当前被关闭的规则。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "rule_name": {"type": "string"},
                        "show_all": {"type": "boolean"},
                    },
                },
            ),
            self._tool_get_rule_status,
        )
        self.tool_registry.register(
            LLMToolSpec(
                name="search_recent_messages",
                description="查看当前群最近消息，可按关键词过滤，只检索触发前短期缓冲里的消息。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                },
            ),
            self._tool_search_recent_messages,
        )
        self.tool_registry.register(
            LLMToolSpec(
                name="get_llm_status",
                description="查看当前群 LLM 状态，可选返回简版状态或当前详细配置。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "detail": {"type": "string", "enum": ["status", "current"]},
                    },
                },
            ),
            self._tool_get_llm_status,
        )
        self.tool_registry.register(
            LLMToolSpec(
                name="get_current_model",
                description="查看当前群正在使用的 provider、model、persona 和触发方式。",
                input_schema={
                    "type": "object",
                    "properties": {},
                },
            ),
            self._tool_get_current_model,
        )

    def register_tool(self, spec: LLMToolSpec, handler) -> None:
        self.tool_registry.register(spec, handler)

    def bind_group_stats_tracker(self, tracker: "GroupStatsTracker | None") -> None:
        self.stats_tracker = tracker

    def bind_rule_switch(self, rule_switch: "GroupRuleSwitch | None") -> None:
        self.rule_switch = rule_switch

    def bind_recent_message_buffer(self, buffer: "RecentMessageBuffer | None") -> None:
        self.recent_message_buffer = buffer

    def _clear_mcp_tools(self) -> None:
        for name in self._mcp_tool_names:
            self.tool_registry.unregister(name)
        self._mcp_tool_names.clear()

    def _register_mcp_tools(self) -> None:
        self._clear_mcp_tools()
        for binding in self.mcp_manager.bindings.values():
            async def _handler(arguments, context, *, alias=binding.alias):
                return await self.mcp_manager.execute(alias, arguments, context)

            self.tool_registry.register(
                LLMToolSpec(
                    name=binding.alias,
                    description=f"[MCP/{binding.server_id}] {binding.description}",
                    input_schema=binding.input_schema,
                ),
                _handler,
            )
            self._mcp_tool_names.add(binding.alias)

    async def ensure_mcp_ready(self, force: bool = False) -> None:
        async with self._mcp_lock:
            if not force and not self._mcp_dirty:
                return
            await self.mcp_manager.sync(self.config.mcp)
            self._register_mcp_tools()
            self._mcp_dirty = False

    def _is_mcp_initializing(self) -> bool:
        return self._mcp_startup_task is not None and not self._mcp_startup_task.done()

    async def _run_mcp_startup(self, force: bool) -> None:
        try:
            await self.ensure_mcp_ready(force=force)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MCP background startup failed")
        finally:
            self._mcp_startup_task = None

    def start_mcp_background(self, force: bool = False) -> None:
        if self._is_mcp_initializing():
            return
        self._mcp_startup_task = asyncio.create_task(
            self._run_mcp_startup(force=force),
            name="quickquip-mcp-startup",
        )

    async def startup(self, *, background: bool = False) -> None:
        if background:
            self.start_mcp_background(force=True)
            return
        await self.ensure_mcp_ready(force=True)

    async def shutdown(self) -> None:
        if self._mcp_startup_task is not None:
            self._mcp_startup_task.cancel()
            await asyncio.gather(self._mcp_startup_task, return_exceptions=True)
            self._mcp_startup_task = None
        await self.mcp_manager.aclose()

    async def reload_runtime(self, *, background: bool = False) -> LLMConfig:
        self.reload_config()
        if background:
            self.start_mcp_background(force=True)
            return self.config
        await self.ensure_mcp_ready(force=True)
        return self.config

    async def _tool_get_identity(self, arguments: dict[str, object], context: ToolExecutionContext) -> str:
        query = str(arguments.get("query", "")).strip()
        matches = self.identities.search(query, limit=5)
        if not matches:
            return f"未找到与“{query}”匹配的身份信息。"

        lines = [f"身份查询：{query}"]
        for entry in matches:
            lines.append(f"- 标准身份：{entry.canonical_name}")
            lines.append(f"  QQ：{'、'.join(entry.qq_ids)}")
            if entry.aliases:
                lines.append(f"  别名：{'、'.join(entry.aliases)}")
            if entry.note:
                lines.append(f"  备注：{entry.note}")
        return "\n".join(lines)

    async def _tool_list_memories(self, arguments: dict[str, object], context: ToolExecutionContext) -> str:
        keyword = str(arguments.get("keyword", "")).strip() or None
        items = self.list_memories(context.group_id, keyword=keyword, chat_type=context.chat_type)
        if not items:
            if keyword:
                return f"{self._scope_subject(context.chat_type)}没有包含“{keyword}”的已存记忆。"
            return f"{self._scope_subject(context.chat_type)}没有已存记忆。"

        lines = [f"{self._memory_label(context.chat_type)}："]
        for item in items[:10]:
            lines.append(f"- #{item['id']} {item['content']}")
        return "\n".join(lines)

    async def _tool_search_web(self, arguments: dict[str, object], context: ToolExecutionContext) -> str:
        _ = context
        query = str(arguments.get("query", "")).strip()
        topic = str(arguments.get("topic", "general")).strip() or "general"
        response = await build_search_client().search(query, topic=topic, max_results=5)
        return format_search_response(response, include_answer=True, max_results=3)

    async def _tool_get_group_stats(
        self,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> str:
        if context.chat_type == "private":
            return "当前私聊没有群消息统计。"
        if self.stats_tracker is None:
            return "当前运行时没有接入群消息统计。"

        top_n = int(arguments.get("top_n", 5) or 5)
        top_n = max(1, min(top_n, 10))
        stats = self.stats_tracker.get_stats(context.group_id)
        if stats is None or stats.total_messages == 0:
            return "当前群暂无统计数据。"

        lines = ["当前群统计：", f"- 消息总数：{stats.total_messages}"]
        if stats.user_messages:
            top_users = sorted(stats.user_messages.items(), key=lambda item: (-item[1], item[0]))[:top_n]
            lines.append(f"- 活跃用户 Top {len(top_users)}：")
            for rank, (user_id, count) in enumerate(top_users, 1):
                display_name = stats.user_names.get(user_id, user_id)
                lines.append(f"  {rank}. {display_name}（QQ {user_id}）— {count} 条")
        if stats.rule_triggers:
            top_rules = sorted(stats.rule_triggers.items(), key=lambda item: (-item[1], item[0]))[:top_n]
            lines.append(f"- 规则触发 Top {len(top_rules)}：")
            for rank, (rule_name, count) in enumerate(top_rules, 1):
                lines.append(f"  {rank}. {rule_name} — {count} 次")
        return "\n".join(lines)

    async def _tool_get_rule_status(
        self,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> str:
        if context.chat_type == "private":
            return "当前私聊没有群规则开关。"
        if self.rule_switch is None:
            return "当前运行时没有接入群规则开关状态。"

        from quickquip.chat.rule_switch import SWITCHABLE_RULES

        rule_name = str(arguments.get("rule_name", "")).strip()
        show_all = bool(arguments.get("show_all", False))
        disabled_set = self.rule_switch.list_disabled(context.group_id)

        if rule_name:
            if rule_name not in SWITCHABLE_RULES:
                return f"未知规则：{rule_name}"
            status = "OFF" if rule_name in disabled_set else "ON"
            return f"规则状态：{rule_name} = {status}"

        if not show_all:
            if not disabled_set:
                return "当前群所有可切换规则都处于开启状态。"
            lines = [f"当前群已关闭规则（{len(disabled_set)}）："]
            for item in sorted(disabled_set):
                lines.append(f"- {item}")
            return "\n".join(lines)

        lines = ["当前群规则状态："]
        for item in sorted(SWITCHABLE_RULES):
            status = "OFF" if item in disabled_set else "ON"
            lines.append(f"- {item}: {status}")
        return "\n".join(lines)

    async def _tool_search_recent_messages(
        self,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> str:
        if self.recent_message_buffer is None:
            return "当前运行时没有接入最近消息缓冲区。"

        query = str(arguments.get("query", "")).strip()
        limit = int(arguments.get("limit", 5) or 5)
        limit = max(1, min(limit, MAX_TRIGGER_CONTEXT_MESSAGES))
        recent_items = self.recent_message_buffer.list_recent(
            self._context_scope_key(context),
            limit=MAX_TRIGGER_CONTEXT_MESSAGES,
        )
        if not recent_items:
            if context.chat_type == "private":
                return "当前私聊最近消息缓冲区为空。"
            return "当前群最近消息缓冲区为空。"

        filtered_items = recent_items
        if query:
            query_lower = query.lower()
            filtered_items = [
                item
                for item in recent_items
                if query in item["text"]
                or query in item["sender_name"]
                or query in item.get("canonical_name", "")
                or query == item["user_id"]
                or query_lower in item["text"].lower()
                or query_lower in item["sender_name"].lower()
                or query_lower in item.get("canonical_name", "").lower()
            ]
        if not filtered_items:
            return f"最近消息里没有匹配“{query}”的内容。"

        selected_items = list(reversed(filtered_items[-limit:]))
        if context.chat_type == "private":
            header = f"最近私聊消息检索：{query}" if query else "最近私聊消息："
        else:
            header = f"最近消息检索：{query}" if query else "最近消息："
        lines = [header]
        for index, item in enumerate(selected_items, 1):
            sender_name = item["sender_name"].strip() or item["user_id"]
            canonical_name = item.get("canonical_name", "").strip()
            user_id = item["user_id"]
            if canonical_name and canonical_name != sender_name:
                speaker = f"{canonical_name}（QQ {user_id}，当前显示名：{sender_name}）"
            elif canonical_name:
                speaker = f"{canonical_name}（QQ {user_id}）"
            else:
                speaker = f"{sender_name}（QQ {user_id}）"
            lines.append(f"{index}. {speaker}：{item['text']}")
        return "\n".join(lines)

    async def _tool_get_llm_status(
        self,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> str:
        detail = str(arguments.get("detail", "status")).strip() or "status"
        if detail == "current":
            return self.format_current(context.group_id, chat_type=context.chat_type)
        return self.format_status(context.group_id, chat_type=context.chat_type)

    async def _tool_get_current_model(
        self,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> str:
        _ = arguments
        settings = self.get_chat_settings(context.group_id, chat_type=context.chat_type)
        lines = [f"{self._model_label(context.chat_type)}："]
        lines.append(f"- Provider：{settings.provider_id}")
        lines.append(f"- Model：{settings.model}")
        lines.append(f"- Persona：{settings.persona_id}")
        lines.append(f"- 前缀触发：{'ON' if settings.allow_prefix else 'OFF'} ({settings.trigger_prefix})")
        if context.chat_type == "private":
            lines.append("- 艾特触发：OFF（私聊不适用）")
        else:
            lines.append(f"- 艾特触发：{'ON' if settings.allow_at else 'OFF'}")
        return "\n".join(lines)

    def reload_config(self) -> LLMConfig:
        self.config = load_llm_config(self.config_path)
        self.vocab = VocabIndex.from_file(self.vocab_path)
        self.identities = IdentityIndex.from_file(self.identity_path)
        self._mcp_dirty = True
        return self.config

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

    def _get_enabled_tool_specs(self, chat_type: str = "group") -> list[LLMToolSpec]:
        return self.tool_registry.list_specs(self._get_enabled_tool_names(chat_type=chat_type))

    def _get_mcp_statuses(self) -> list[MCPServerStatus]:
        return self.mcp_manager.get_statuses()

    def format_mcp_status(self) -> str:
        lines = ["MCP 状态"]
        if not self.config.mcp.enabled:
            lines.append("总开关：OFF")
            return "\n".join(lines)

        lines.append("总开关：ON")
        if self._is_mcp_initializing():
            lines.append("运行态：初始化中")
        if self._mcp_dirty and not self._get_mcp_statuses():
            lines.append("运行态：待初始化")
            return "\n".join(lines)

        statuses = self._get_mcp_statuses()
        if not statuses:
            lines.append("当前没有已配置的 MCP servers")
            return "\n".join(lines)

        connected = sum(1 for item in statuses if item.connected)
        lines.append(f"连接数：{connected}/{len(statuses)}")
        lines.append(f"工具数：{len(self._mcp_tool_names)}")
        for status in statuses:
            state = "ON" if status.connected else ("OFF" if not status.enabled else "ERROR")
            lines.append(
                f"- {status.id} [{status.transport}] {state} tools={status.tool_count}"
                + (f" detail={status.detail}" if status.detail else "")
                + (f" error={status.error}" if status.error else "")
            )
        return "\n".join(lines)

    def _summarize_mcp_status(self) -> str:
        if not self.config.mcp.enabled:
            return "OFF"
        if self._is_mcp_initializing():
            return "初始化中"
        statuses = self._get_mcp_statuses()
        if self._mcp_dirty and not statuses:
            return "待初始化"
        if not statuses:
            return "ON (0/0)"
        connected = sum(1 for item in statuses if item.connected)
        return f"ON ({connected}/{len(statuses)}，{len(self._mcp_tool_names)} tools)"

    def list_providers(self) -> list[ProviderConfig]:
        return list(self.config.providers.values())

    def list_personas(self, chat_type: str = "group") -> list[PersonaConfig]:
        return [p for p in self.config.personas.values() if not p.scope or chat_type in p.scope]

    def format_status(self, group_id: int | str, chat_type: str = "group") -> str:
        settings = self.get_chat_settings(group_id, chat_type=chat_type)
        lines = ["LLM 状态"]
        if self.config.load_error:
            lines.append(f"配置：{self.config.load_error}")
            return "\n".join(lines)

        lines.append(f"当前会话：{self._scope_label(chat_type)}")
        lines.append(f"总开关：{'ON' if settings.enabled else 'OFF'}")
        lines.append(f"记忆注入：{'ON' if settings.memory_enabled else 'OFF'}")
        lines.append(f"工具调用：{'ON' if self.config.runtime.tool_calling_enabled else 'OFF'}")
        lines.append(f"MCP：{self._summarize_mcp_status()}")
        lines.append(f"Provider：{settings.provider_id}")
        lines.append(f"Model：{settings.model}")
        lines.append(f"Persona：{settings.persona_id}")
        lines.append(f"前缀触发：{'ON' if settings.allow_prefix else 'OFF'} ({settings.trigger_prefix})")
        if chat_type == "private":
            lines.append(f"会话状态：{'进行中' if settings.enabled else '未开启'}")
            lines.append("直聊触发：仅在会话开启后生效")
            lines.append("艾特触发：OFF（私聊不适用）")
            lines.append("临时上下文：私聊不额外注入群消息")
        else:
            lines.append(f"艾特触发：{'ON' if settings.allow_at else 'OFF'}")
            lines.append(f"临时上下文：触发前最多 {MAX_TRIGGER_CONTEXT_MESSAGES} 条群消息")
        return "\n".join(lines)

    def format_current(self, group_id: int | str, chat_type: str = "group") -> str:
        settings = self.get_chat_settings(group_id, chat_type=chat_type)
        lines = ["LLM 当前配置"]
        if self.config.load_error:
            lines.append(f"配置：{self.config.load_error}")
            return "\n".join(lines)

        scope_key = self.build_chat_scope_key(group_id, chat_type)
        default_history_limit = self._default_history_limit(chat_type)
        effective_history_limit = settings.history_limit if settings.history_limit is not None else default_history_limit
        history_limit_note = (
            f"（会话覆盖，默认 {default_history_limit}）"
            if settings.history_limit is not None
            else f"（默认 {default_history_limit}）"
        )
        lines.append(f"总开关：{'ON' if settings.enabled else 'OFF'}")
        lines.append(f"当前会话：{self._scope_label(chat_type)}")
        lines.append(f"记忆注入：{'ON' if settings.memory_enabled else 'OFF'}")
        lines.append(f"工具调用：{'ON' if self.config.runtime.tool_calling_enabled else 'OFF'}")
        lines.append(f"MCP：{self._summarize_mcp_status()}")
        lines.append(f"工具列表：{', '.join(self._get_enabled_tool_names(chat_type=chat_type)) or '无'}")
        lines.append(f"Provider：{settings.provider_id}")
        lines.append(f"Model：{settings.model}")
        lines.append(f"Persona：{settings.persona_id}")
        lines.append(f"前缀触发：{'ON' if settings.allow_prefix else 'OFF'} ({settings.trigger_prefix})")
        if chat_type == "private":
            lines.append(f"会话状态：{'进行中' if settings.enabled else '未开启'}")
            lines.append("直聊触发：仅在会话开启后生效")
            lines.append("艾特触发：OFF（私聊不适用）")
        else:
            lines.append(f"艾特触发：{'ON' if settings.allow_at else 'OFF'}")
        lines.append(
            f"短期会话：已存 {self.store.count_conversation_messages(scope_key)} 条 / 读取上限 {effective_history_limit} 条{history_limit_note}"
        )
        lines.append(
            f"长期记忆：已存 {self.store.count_memories(scope_key)} 条 / 上限 {MAX_STORED_MEMORY_ITEMS} 条"
        )
        if chat_type == "private":
            lines.append("临时上下文：私聊不额外注入群消息")
        else:
            lines.append(f"临时上下文：仅触发当下向前最多 {MAX_TRIGGER_CONTEXT_MESSAGES} 条群消息")
        return "\n".join(lines)

    def set_chat_enabled(self, chat_id: int | str, enabled: bool, chat_type: str = "group") -> None:
        self._update_chat_settings(chat_id, chat_type, enabled=int(enabled))

    def start_private_session(self, user_id: int | str, *, preset: str = "") -> None:
        scope_key = self.build_chat_scope_key(user_id, "private")
        self.clear_context(user_id, chat_type="private")
        self._session_presets.pop(scope_key, None)
        self.set_chat_enabled(user_id, True, chat_type="private")
        if preset.strip():
            self._session_presets[scope_key] = preset.strip()

    def end_private_session(self, user_id: int | str, *, save: bool = True) -> dict:
        scope_key = self.build_chat_scope_key(user_id, "private")
        user_id_str = str(user_id)
        msg_count = self.store.count_conversation_messages(scope_key)
        archive_number = None

        if save and msg_count > 0:
            archive_number = self.store.get_next_archive_number(user_id_str)
            settings = self.get_chat_settings(user_id, chat_type="private")
            preset = self._session_presets.get(scope_key, "")
            created_at = self.store.get_earliest_message_time(scope_key)
            self.store.create_session_archive(
                user_id_str,
                archive_number,
                persona_id=settings.persona_id or None,
                preset=preset or None,
                message_count=msg_count,
                created_at=created_at,
            )
            self.store.archive_conversation_messages(user_id_str, archive_number)
        else:
            self.store.clear_conversation_messages(scope_key)

        self.set_chat_enabled(user_id, False, chat_type="private")
        self._session_presets.pop(scope_key, None)
        return {"deleted": msg_count, "archive_number": archive_number}

    def resume_private_session(self, user_id: int | str, archive_number: int | None = None) -> dict:
        user_id_str = str(user_id)
        if archive_number is None:
            archive_number = self.store.get_latest_archive_number(user_id_str)
            if archive_number is None:
                return {"error": "没有可恢复的存档"}

        archive = self.store.get_session_archive(user_id_str, archive_number)
        if archive is None:
            return {"error": f"存档 #{archive_number} 不存在"}

        scope_key = self.build_chat_scope_key(user_id, "private")
        current_count = self.store.count_conversation_messages(scope_key)
        if current_count > 0:
            self.store.clear_conversation_messages(scope_key)

        self.store.restore_conversation_messages(user_id_str, archive_number)
        self._session_presets.pop(scope_key, None)
        preset = archive.get("preset") or ""
        if preset:
            self._session_presets[scope_key] = preset
        self.set_chat_enabled(user_id, True, chat_type="private")
        self.store.delete_session_archive(user_id_str, archive_number)

        return {
            "archive_number": archive_number,
            "message_count": archive.get("message_count", 0),
            "preset": preset,
            "persona_id": archive.get("persona_id") or "",
        }

    def format_session_archives(self, user_id: int | str) -> str:
        archives = self.store.list_session_archives(str(user_id))
        if not archives:
            return "暂无存档"
        lines = ["存档列表："]
        for a in reversed(archives):
            num = a["archive_number"]
            ts = (a.get("created_at") or "")[:16].replace("T", " ")
            count = a.get("message_count", 0)
            persona = a.get("persona_id") or "default"
            line = f"  #{num}  {ts}  {count}条  人格:{persona}"
            preset = a.get("preset") or ""
            if preset:
                preview = preset[:30] + ("..." if len(preset) > 30 else "")
                line += f"  附加:{preview}"
            lines.append(line)
        return "\n".join(lines)

    def delete_session_archive_for_user(self, user_id: int | str, archive_number: int) -> bool:
        return self.store.delete_session_archive(str(user_id), archive_number)

    def get_session_preset(self, scope_key: str) -> str:
        return self._session_presets.get(scope_key, "")

    def set_group_enabled(self, group_id: int | str, enabled: bool) -> None:
        self.set_chat_enabled(group_id, enabled, chat_type="group")

    def set_chat_memory_enabled(self, chat_id: int | str, enabled: bool, chat_type: str = "group") -> None:
        self._update_chat_settings(chat_id, chat_type, memory_enabled=int(enabled))

    def set_group_memory_enabled(self, group_id: int | str, enabled: bool) -> None:
        self.set_chat_memory_enabled(group_id, enabled, chat_type="group")

    def set_chat_history_limit(self, chat_id: int | str, limit: int, chat_type: str = "group") -> None:
        self._update_chat_settings(chat_id, chat_type, history_limit=limit)

    def set_group_history_limit(self, group_id: int | str, limit: int) -> None:
        self.set_chat_history_limit(group_id, limit, chat_type="group")

    def reset_chat_history_limit(self, chat_id: int | str, chat_type: str = "group") -> None:
        self._update_chat_settings(chat_id, chat_type, history_limit=None)

    def reset_group_history_limit(self, group_id: int | str) -> None:
        self.reset_chat_history_limit(group_id, chat_type="group")

    def set_chat_model(self, chat_id: int | str, provider_id: str, model: str, chat_type: str = "group") -> str:
        provider = self.config.providers.get(provider_id)
        if provider is None:
            raise ValueError(f"未知 provider：{provider_id}")
        if model not in provider.models:
            raise ValueError(f"provider {provider_id} 未声明模型：{model}")
        self._update_chat_settings(chat_id, chat_type, provider_id=provider_id, model=model)
        return model

    def set_group_model(self, group_id: int | str, provider_id: str, model: str) -> str:
        return self.set_chat_model(group_id, provider_id, model, chat_type="group")

    def set_chat_persona(self, chat_id: int | str, persona_id: str, chat_type: str = "group") -> None:
        if persona_id not in self.config.personas:
            raise ValueError(f"未知 persona：{persona_id}")
        self._update_chat_settings(chat_id, chat_type, persona_id=persona_id)

    def set_group_persona(self, group_id: int | str, persona_id: str) -> None:
        self.set_chat_persona(group_id, persona_id, chat_type="group")

    def set_chat_trigger_prefix(self, chat_id: int | str, prefix: str, chat_type: str = "group") -> None:
        prefix = prefix.strip()
        if not prefix:
            raise ValueError("触发前缀不能为空")
        self._update_chat_settings(chat_id, chat_type, trigger_prefix=prefix)

    def set_group_trigger_prefix(self, group_id: int | str, prefix: str) -> None:
        self.set_chat_trigger_prefix(group_id, prefix, chat_type="group")

    def set_chat_allow_prefix(self, chat_id: int | str, enabled: bool, chat_type: str = "group") -> None:
        self._update_chat_settings(chat_id, chat_type, allow_prefix=int(enabled))

    def set_group_allow_prefix(self, group_id: int | str, enabled: bool) -> None:
        self.set_chat_allow_prefix(group_id, enabled, chat_type="group")

    def set_group_allow_at(self, group_id: int | str, enabled: bool) -> None:
        self._update_chat_settings(group_id, "group", allow_at=int(enabled))

    def remember_memory(self, chat_id: int | str, content: str, chat_type: str = "group") -> int:
        scope_key = self.build_chat_scope_key(chat_id, chat_type)
        memory_id = self.store.add_memory(scope_key, content.strip(), scope="group", source="manual")
        self.store.prune_memories(
            scope_key,
            min(self.config.runtime.memory_max_items_per_group, MAX_STORED_MEMORY_ITEMS),
        )
        return memory_id

    def remember_group_memory(self, group_id: int | str, content: str) -> int:
        return self.remember_memory(group_id, content, chat_type="group")

    def list_memories(self, chat_id: int | str, keyword: str | None = None, chat_type: str = "group") -> list[dict[str, object]]:
        return self.store.list_memories(self.build_chat_scope_key(chat_id, chat_type), limit=10, keyword=keyword)

    def list_group_memories(self, group_id: int | str, keyword: str | None = None) -> list[dict[str, object]]:
        return self.list_memories(group_id, keyword=keyword, chat_type="group")

    def forget_memories(self, chat_id: int | str, keyword: str, chat_type: str = "group") -> int:
        return self.store.delete_memories(self.build_chat_scope_key(chat_id, chat_type), keyword.strip())

    def forget_group_memories(self, group_id: int | str, keyword: str) -> int:
        return self.forget_memories(group_id, keyword, chat_type="group")

    def clear_memories(self, chat_id: int | str, chat_type: str = "group") -> int:
        return self.store.clear_memories(self.build_chat_scope_key(chat_id, chat_type))

    def clear_group_memories(self, group_id: int | str) -> int:
        return self.clear_memories(group_id, chat_type="group")

    def format_providers(self) -> str:
        if self.config.load_error:
            return f"LLM 配置不可用：{self.config.load_error}"
        lines = ["可用 Providers："]
        for provider in self.list_providers():
            lines.append(f"- {provider.id} [{provider.protocol}] 默认模型：{provider.default_model}")
        return "\n".join(lines)

    def format_models(self, provider_id: str | None = None) -> str:
        if self.config.load_error:
            return f"LLM 配置不可用：{self.config.load_error}"
        if provider_id:
            provider = self.config.providers.get(provider_id)
            if provider is None:
                return f"未知 provider：{provider_id}"
            return "\n".join([f"{provider.id} 可用模型：", *[f"- {model}" for model in provider.models]])

        lines = ["可用模型："]
        for provider in self.list_providers():
            lines.append(f"[{provider.id}]")
            lines.extend(f"- {model}" for model in provider.models)
        return "\n".join(lines)

    def format_personas(self, chat_type: str = "group") -> str:
        if self.config.load_error:
            return f"LLM 配置不可用：{self.config.load_error}"
        lines = ["可用人格："]
        for persona in self.list_personas(chat_type=chat_type):
            lines.append(f"- {persona.id}：{persona.display_name}")
        return "\n".join(lines)

    def format_memories(self, group_id: int | str, keyword: str | None = None, chat_type: str = "group") -> str:
        memories = self.list_memories(group_id, keyword=keyword, chat_type=chat_type)
        if not memories:
            return f"{self._scope_subject(chat_type)}没有已保存记忆"
        lines = [f"{self._memory_label(chat_type)}："]
        for item in memories:
            lines.append(f"- #{item['id']} {item['content']}")
        return "\n".join(lines)

    def format_memory_status(self, group_id: int | str, chat_type: str = "group") -> str:
        settings = self.get_chat_settings(group_id, chat_type=chat_type)
        total = self.store.count_memories(self.build_chat_scope_key(group_id, chat_type))
        lines = ["记忆状态"]
        lines.append(f"当前会话：{self._scope_label(chat_type)}")
        lines.append(f"记忆注入：{'ON' if settings.memory_enabled else 'OFF'}")
        lines.append(f"已存条数：{total}")
        lines.append(f"检索上限：{MAX_MEMORY_RETRIEVAL_ITEMS}")
        lines.append(f"存储上限：{MAX_STORED_MEMORY_ITEMS}")
        return "\n".join(lines)

    def clear_context(self, group_id: int | str, chat_type: str = "group") -> int:
        return self.store.clear_conversation_messages(self.build_chat_scope_key(group_id, chat_type))

    def clear_group_context(self, group_id: int | str) -> int:
        return self.clear_context(group_id, chat_type="group")

    def delete_message_from_context(self, scope_key: str, message_id: str) -> bool:
        db_deleted = self.store.delete_conversation_message_by_message_id(scope_key, message_id)
        buf_deleted = self.recent_message_buffer.remove_by_message_id(scope_key, message_id) if self.recent_message_buffer else False
        return db_deleted > 0 or buf_deleted

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
            identities=self.identities,
            vocab=self.vocab,
            beijing_timezone=BEIJING_TIMEZONE,
            search_tool_name=SEARCH_TOOL_NAME,
            get_search_backend_name=get_search_backend_name,
            chat_type=chat_type,
            participants=participants,
            provider_style_overrides=provider_style_overrides,
            session_preset=session_preset,
        )

    def _merge_image_urls(self, *collections: list[str]) -> list[str]:
        return merge_image_urls(*collections)


    def _build_user_message_content(
        self,
        *,
        prompt: str,
        quoted_text: str = "",
        quoted_sender_name: str = "",
        quoted_user_id: str = "",
        quoted_image_urls: list[str] | None = None,
        sender_name: str = "",
        user_id: str = "",
    ) -> str:
        return build_user_message_content(
            prompt=prompt,
            quoted_text=quoted_text,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
            quoted_image_urls=quoted_image_urls,
            max_quoted_message_chars=MAX_QUOTED_MESSAGE_CHARS,
            identities=self.identities,
            sender_name=sender_name,
            user_id=str(user_id),
        )

    def _build_messages(
        self,
        *,
        prompt: str,
        image_urls: list[str],
        history: list[dict[str, str]],
        recent_messages: list[dict[str, str]] | None,
        chat_type: str = "group",
    ) -> list[LLMConversationMessage]:
        return build_messages(
            prompt=prompt,
            image_urls=image_urls,
            history=history,
            recent_messages=recent_messages,
            max_trigger_context_messages=MAX_TRIGGER_CONTEXT_MESSAGES,
            chat_type=chat_type,
            identities=self.identities,
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
    ) -> list[dict[str, str]]:
        participants: list[dict[str, str]] = []
        seen_user_ids: set[str] = set()

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
                identity = self.identities.resolve_user(user_key, sender_value)
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
            get_search_backend_name=get_search_backend_name,
            search_tool_name=SEARCH_TOOL_NAME,
            search_failsafe_max_rounds=SEARCH_TOOL_FAILSAFE_MAX_ROUNDS,
            search_failsafe_max_calls_per_round=SEARCH_TOOL_FAILSAFE_MAX_CALLS_PER_ROUND,
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
        message_id: str | None = None,
    ) -> dict[str, str]:
        prompt = prompt.strip()
        normalized_image_urls = [url for url in (image_urls or []) if url.strip()]
        normalized_quoted_text = quoted_text.strip()
        normalized_quoted_image_urls = [url for url in (quoted_image_urls or []) if url.strip()]
        if not prompt and normalized_image_urls and not normalized_quoted_text and not normalized_quoted_image_urls:
            prompt = "请描述这张图片，并优先回答群友最可能想知道的内容。"

        if not prompt and not normalized_quoted_text and not normalized_image_urls and not normalized_quoted_image_urls:
            return {
                "reply": self.config.triggers.empty_prompt_reply,
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        if self.config.load_error:
            return {
                "reply": f"LLM 配置不可用：{self.config.load_error}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        scope_key = self.build_chat_scope_key(chat_id, chat_type)
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
        effective_prompt = self._build_user_message_content(
            prompt=trimmed_prompt,
            quoted_text=quoted_prompt,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
            quoted_image_urls=normalized_quoted_image_urls,
            sender_name=sender_name,
            user_id=str(user_id),
        )[: self.config.runtime.max_prompt_chars]
        effective_image_urls = self._merge_image_urls(normalized_image_urls, normalized_quoted_image_urls)
        default_history_limit = self._default_history_limit(chat_type)
        history = self.store.list_recent_conversation_messages(
            scope_key,
            min(
                settings.history_limit if settings.history_limit is not None else default_history_limit,
                self._max_stored_conversation_messages(chat_type),
            ),
        )
        participants = self._collect_known_participants(
            user_id=user_id,
            sender_name=sender_name,
            history=history,
            recent_messages=recent_messages,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
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
            prompt=effective_prompt,
            image_urls=effective_image_urls,
            history=history,
            recent_messages=recent_messages,
            chat_type=chat_type,
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

        current_identity = self.identities.resolve_user(user_id, sender_name)
        self.store.append_conversation_message(
            scope_key,
            user_id,
            "user",
            effective_prompt,
            sender_name=sender_name,
            canonical_name=current_identity.canonical_name,
            message_id=str(message_id) if message_id else None,
        )
        self.store.append_conversation_message(scope_key, None, "assistant", text)
        self.store.prune_conversation_messages(
            scope_key,
            self._history_retention_limit(chat_type),
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
            message_id=message_id,
        )


llm_service = LLMService()
