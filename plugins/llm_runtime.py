from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import re
import asyncio
from zoneinfo import ZoneInfo

from plugins.llm_config import LLMConfig, PersonaConfig, ProviderConfig, load_llm_config
from plugins.llm_identity import IdentityEntry, IdentityIndex
from plugins.llm_mcp import MCPClientManager, MCPServerStatus
from plugins.llm_provider import LLMProviderError, LLMRequest, build_provider_client
from plugins.llm_store import LLMStore
from plugins.llm_tool_registry import ToolRegistry
from plugins.llm_tools import (
    LLMConversationMessage,
    LLMToolCall,
    LLMToolResult,
    LLMToolSpec,
    ToolExecutionContext,
)
from plugins.message_stats import GroupStatsTracker
from plugins.recent_message_buffer import RecentMessageBuffer
from plugins.rule_switch import GroupRuleSwitch, SWITCHABLE_RULES
from plugins.llm_vocab import VocabIndex
from plugins.web_search import build_search_client, format_search_response, get_search_backend_name
from plugins.tz_config import BEIJING_TIMEZONE


CONFIG_PATH = Path("config/llm.toml")
DB_PATH = Path("data/llm.db")
VOCAB_PATH = Path("dev/llm_about/vocab.yaml")
IDENTITY_PATH = Path("dev/llm_about/identities.yaml")
LLM_RULE_NAME = "llm_chat"
MAX_TRIGGER_CONTEXT_MESSAGES = 20
MAX_CONVERSATION_HISTORY_MESSAGES = 20
MAX_STORED_CONVERSATION_MESSAGES = 20
MAX_MEMORY_RETRIEVAL_ITEMS = 8
MAX_STORED_MEMORY_ITEMS = 200
SEARCH_TOOL_NAME = "search_web"
SEARCH_TOOL_FAILSAFE_MAX_ROUNDS = 64
SEARCH_TOOL_FAILSAFE_MAX_CALLS_PER_ROUND = 64
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

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ResolvedGroupSettings:
    enabled: bool
    memory_enabled: bool
    provider_id: str
    model: str
    persona_id: str
    trigger_prefix: str
    allow_prefix: bool
    allow_at: bool


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
        self.stats_tracker: GroupStatsTracker | None = None
        self.rule_switch: GroupRuleSwitch | None = None
        self.recent_message_buffer: RecentMessageBuffer | None = None
        self._mcp_tool_names: set[str] = set()
        self._mcp_dirty = True
        self._mcp_lock = asyncio.Lock()
        self._mcp_startup_task: asyncio.Task[None] | None = None
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

    def bind_group_stats_tracker(self, tracker: GroupStatsTracker | None) -> None:
        self.stats_tracker = tracker

    def bind_rule_switch(self, rule_switch: GroupRuleSwitch | None) -> None:
        self.rule_switch = rule_switch

    def bind_recent_message_buffer(self, buffer: RecentMessageBuffer | None) -> None:
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
        items = self.list_group_memories(context.group_id, keyword=keyword)
        if not items:
            if keyword:
                return f"当前群没有包含“{keyword}”的已存记忆。"
            return "当前群没有已存记忆。"

        lines = ["当前群记忆："]
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
        if self.stats_tracker is None:
            return "当前运行时没有接入群消息统计。"

        top_n = int(arguments.get("top_n", 5) or 5)
        top_n = max(1, min(top_n, 10))
        stats = self.stats_tracker.get_stats(context.group_id)
        if stats is None or stats.total_messages == 0:
            return "当前群暂无统计数据。"

        lines = [f"当前群统计：", f"- 消息总数：{stats.total_messages}"]
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
        if self.rule_switch is None:
            return "当前运行时没有接入群规则开关状态。"

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
        recent_items = self.recent_message_buffer.list_recent(context.group_id, limit=MAX_TRIGGER_CONTEXT_MESSAGES)
        if not recent_items:
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
            return self.format_current(context.group_id)
        return self.format_status(context.group_id)

    async def _tool_get_current_model(
        self,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> str:
        _ = arguments
        settings = self.get_group_settings(context.group_id)
        lines = ["当前群模型配置："]
        lines.append(f"- Provider：{settings.provider_id}")
        lines.append(f"- Model：{settings.model}")
        lines.append(f"- Persona：{settings.persona_id}")
        lines.append(f"- 前缀触发：{'ON' if settings.allow_prefix else 'OFF'} ({settings.trigger_prefix})")
        lines.append(f"- 艾特触发：{'ON' if settings.allow_at else 'OFF'}")
        return "\n".join(lines)

    def reload_config(self) -> LLMConfig:
        self.config = load_llm_config(self.config_path)
        self.vocab = VocabIndex.from_file(self.vocab_path)
        self.identities = IdentityIndex.from_file(self.identity_path)
        self._mcp_dirty = True
        return self.config

    def get_group_settings(self, group_id: int | str) -> ResolvedGroupSettings:
        overrides = self.store.get_group_settings(group_id)
        provider_id = overrides.provider_id or self.config.runtime.default_provider or ""
        provider = self.config.providers.get(provider_id)
        model = overrides.model or (provider.default_model if provider else "")

        return ResolvedGroupSettings(
            enabled=overrides.enabled if overrides.enabled is not None else self.config.runtime.enabled,
            memory_enabled=(
                overrides.memory_enabled
                if overrides.memory_enabled is not None
                else self.config.runtime.memory_enabled
            ),
            provider_id=provider_id,
            model=model,
            persona_id=overrides.persona_id or self.config.runtime.default_persona or "",
            trigger_prefix=overrides.trigger_prefix or self.config.triggers.default_prefix,
            allow_prefix=(
                overrides.allow_prefix
                if overrides.allow_prefix is not None
                else self.config.triggers.allow_prefix
            ),
            allow_at=overrides.allow_at if overrides.allow_at is not None else self.config.triggers.allow_at,
        )

    def _get_enabled_tool_names(self) -> list[str]:
        names = self.config.tools.enabled or [*DEFAULT_ENABLED_TOOLS, *sorted(self._mcp_tool_names)]
        return [name for name in names if self.tool_registry.has_tool(name)]

    def _get_enabled_tool_specs(self) -> list[LLMToolSpec]:
        return self.tool_registry.list_specs(self._get_enabled_tool_names())

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

    def list_personas(self) -> list[PersonaConfig]:
        return list(self.config.personas.values())

    def format_status(self, group_id: int | str) -> str:
        settings = self.get_group_settings(group_id)
        lines = ["LLM 状态"]
        if self.config.load_error:
            lines.append(f"配置：{self.config.load_error}")
            return "\n".join(lines)

        lines.append(f"总开关：{'ON' if settings.enabled else 'OFF'}")
        lines.append(f"记忆注入：{'ON' if settings.memory_enabled else 'OFF'}")
        lines.append(f"工具调用：{'ON' if self.config.runtime.tool_calling_enabled else 'OFF'}")
        lines.append(f"MCP：{self._summarize_mcp_status()}")
        lines.append(f"Provider：{settings.provider_id}")
        lines.append(f"Model：{settings.model}")
        lines.append(f"Persona：{settings.persona_id}")
        lines.append(f"前缀触发：{'ON' if settings.allow_prefix else 'OFF'} ({settings.trigger_prefix})")
        lines.append(f"艾特触发：{'ON' if settings.allow_at else 'OFF'}")
        lines.append(f"临时上下文：触发前最多 {MAX_TRIGGER_CONTEXT_MESSAGES} 条群消息")
        return "\n".join(lines)

    def format_current(self, group_id: int | str) -> str:
        settings = self.get_group_settings(group_id)
        lines = ["LLM 当前配置"]
        if self.config.load_error:
            lines.append(f"配置：{self.config.load_error}")
            return "\n".join(lines)

        lines.append(f"总开关：{'ON' if settings.enabled else 'OFF'}")
        lines.append(f"记忆注入：{'ON' if settings.memory_enabled else 'OFF'}")
        lines.append(f"工具调用：{'ON' if self.config.runtime.tool_calling_enabled else 'OFF'}")
        lines.append(f"MCP：{self._summarize_mcp_status()}")
        lines.append(f"工具列表：{', '.join(self._get_enabled_tool_names()) or '无'}")
        lines.append(f"Provider：{settings.provider_id}")
        lines.append(f"Model：{settings.model}")
        lines.append(f"Persona：{settings.persona_id}")
        lines.append(f"前缀触发：{'ON' if settings.allow_prefix else 'OFF'} ({settings.trigger_prefix})")
        lines.append(f"艾特触发：{'ON' if settings.allow_at else 'OFF'}")
        lines.append(
            f"短期会话：已存 {self.store.count_conversation_messages(group_id)} 条 / 上限 {MAX_STORED_CONVERSATION_MESSAGES} 条"
        )
        lines.append(
            f"长期记忆：已存 {self.store.count_memories(group_id)} 条 / 上限 {MAX_STORED_MEMORY_ITEMS} 条"
        )
        lines.append(f"临时上下文：仅触发当下向前最多 {MAX_TRIGGER_CONTEXT_MESSAGES} 条群消息")
        return "\n".join(lines)

    def set_group_enabled(self, group_id: int | str, enabled: bool) -> None:
        self.store.update_group_settings(group_id, enabled=int(enabled))

    def set_group_memory_enabled(self, group_id: int | str, enabled: bool) -> None:
        self.store.update_group_settings(group_id, memory_enabled=int(enabled))

    def set_group_model(self, group_id: int | str, provider_id: str, model: str) -> str:
        provider = self.config.providers.get(provider_id)
        if provider is None:
            raise ValueError(f"未知 provider：{provider_id}")
        if model not in provider.models:
            raise ValueError(f"provider {provider_id} 未声明模型：{model}")
        self.store.update_group_settings(group_id, provider_id=provider_id, model=model)
        return model

    def set_group_persona(self, group_id: int | str, persona_id: str) -> None:
        if persona_id not in self.config.personas:
            raise ValueError(f"未知 persona：{persona_id}")
        self.store.update_group_settings(group_id, persona_id=persona_id)

    def set_group_trigger_prefix(self, group_id: int | str, prefix: str) -> None:
        prefix = prefix.strip()
        if not prefix:
            raise ValueError("触发前缀不能为空")
        self.store.update_group_settings(group_id, trigger_prefix=prefix)

    def set_group_allow_prefix(self, group_id: int | str, enabled: bool) -> None:
        self.store.update_group_settings(group_id, allow_prefix=int(enabled))

    def set_group_allow_at(self, group_id: int | str, enabled: bool) -> None:
        self.store.update_group_settings(group_id, allow_at=int(enabled))

    def remember_group_memory(self, group_id: int | str, content: str) -> int:
        memory_id = self.store.add_memory(group_id, content.strip(), scope="group", source="manual")
        self.store.prune_memories(
            group_id,
            min(self.config.runtime.memory_max_items_per_group, MAX_STORED_MEMORY_ITEMS),
        )
        return memory_id

    def list_group_memories(self, group_id: int | str, keyword: str | None = None) -> list[dict[str, object]]:
        return self.store.list_memories(group_id, limit=10, keyword=keyword)

    def forget_group_memories(self, group_id: int | str, keyword: str) -> int:
        return self.store.delete_memories(group_id, keyword.strip())

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

    def format_personas(self) -> str:
        if self.config.load_error:
            return f"LLM 配置不可用：{self.config.load_error}"
        lines = ["可用人格："]
        for persona in self.list_personas():
            lines.append(f"- {persona.id}：{persona.display_name}")
        return "\n".join(lines)

    def format_memories(self, group_id: int | str, keyword: str | None = None) -> str:
        memories = self.list_group_memories(group_id, keyword=keyword)
        if not memories:
            return "当前群没有已保存记忆"
        lines = ["当前群记忆："]
        for item in memories:
            lines.append(f"- #{item['id']} {item['content']}")
        return "\n".join(lines)

    def format_memory_status(self, group_id: int | str) -> str:
        settings = self.get_group_settings(group_id)
        total = self.store.count_memories(group_id)
        lines = ["记忆状态"]
        lines.append(f"记忆注入：{'ON' if settings.memory_enabled else 'OFF'}")
        lines.append(f"已存条数：{total}")
        lines.append(f"检索上限：{MAX_MEMORY_RETRIEVAL_ITEMS}")
        lines.append(f"存储上限：{MAX_STORED_MEMORY_ITEMS}")
        return "\n".join(lines)

    def clear_group_context(self, group_id: int | str) -> int:
        return self.store.clear_conversation_messages(group_id)

    def _format_identity_entry(self, entry: IdentityEntry) -> str:
        lines = [f"- 标准身份：{entry.canonical_name}"]
        lines.append(f"  QQ：{'、'.join(entry.qq_ids)}")
        if entry.aliases:
            lines.append(f"  别名：{'、'.join(entry.aliases)}")
        if entry.note:
            lines.append(f"  备注：{entry.note}")
        return "\n".join(lines)

    def _build_system_prompt(
        self,
        persona: PersonaConfig,
        group_id: int | str,
        user_id: int | str,
        sender_name: str,
        prompt: str,
        memories: list[dict[str, object]],
        tool_specs: list[LLMToolSpec],
    ) -> str:
        now_cst = datetime.now(ZoneInfo(BEIJING_TIMEZONE))
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        identity = self.identities.resolve_user(user_id, sender_name)

        lines = [persona.system_prompt.strip()]
        if persona.style_prompt.strip():
            lines.append(persona.style_prompt.strip())

        lines.append("当前元数据：")
        lines.append(f"- 当前北京时间：{now_cst:%Y-%m-%d %H:%M}")
        lines.append(f"- 当前星期：{weekday_names[now_cst.weekday()]}")
        lines.append(f"当前群号：{group_id}")
        lines.append(f"当前提问者昵称：{sender_name}")
        lines.append("当前提问者身份：")
        lines.append(f"- QQ：{identity.user_id}")
        lines.append(f"- 当前显示名：{sender_name}")
        if identity.is_registered:
            lines.append(f"- 标准身份：{identity.canonical_name}")
            if identity.aliases:
                lines.append(f"- 常见别名：{'、'.join(identity.aliases)}")
            if identity.note:
                lines.append(f"- 备注：{identity.note}")
        else:
            lines.append("- 标准身份：未登记")
        if memories:
            lines.append("以下是与当前群聊相关的持久记忆，仅在确实相关时参考：")
            for index, memory in enumerate(memories, 1):
                lines.append(f"{index}. {memory['content']}")

        vocab_lines: list[str] = []
        vocab_matches = self.vocab.find_matches(prompt)
        if vocab_matches:
            vocab_lines.append("以下词表命中仅用于帮助你做称呼消歧，不要机械复读：")
            for item in vocab_matches:
                line = f"- {item.alias} 通常指 {item.name}"
                if item.note:
                    line += f"；注意：{item.note}"
                vocab_lines.append(line)

        glossary_matches = self.vocab.find_glossary(prompt)
        if glossary_matches:
            vocab_lines.append("以下黑话解释仅在当前话题相关时参考：")
            for term, meaning in glossary_matches:
                vocab_lines.append(f"- {term}：{meaning}")

        if vocab_lines:
            lines.append("\n".join(vocab_lines))

        if tool_specs:
            search_backend = get_search_backend_name()
            backend_label = "SearXNG" if search_backend == "searxng" else "Tavily"
            tool_lines = [
                "工具使用规则：",
                "- 只有在确实需要外部信息、身份查询或记忆查询时才调用工具。",
                "- 优先直接回答，不要为了显得聪明而滥用工具。",
                f"- 当前联网后端：{backend_label}。",
                f"- 遇到需要最新事实、网页、新闻、价格、版本、公告或来源链接的问题时，优先调用 {SEARCH_TOOL_NAME}。",
                "- 工具结果不足时，明确告诉用户不足，不要编造。",
            ]
            if search_backend == "searxng":
                tool_lines.extend([
                    f"- 当前 {SEARCH_TOOL_NAME} 走项目内 SearXNG；搜索结果不够时，可以继续多次调用 {SEARCH_TOOL_NAME} 细化检索。",
                    "- 优先先搜再答，再根据搜索结果组织结论。",
                ])
            tool_lines.extend([
                "当前可用工具：",
            ])
            for spec in tool_specs:
                tool_lines.append(f"- {spec.name}：{spec.description}")
            lines.append("\n".join(tool_lines))

        return "\n\n".join(line for line in lines if line)

    def _normalize_history(
        self,
        history: list[dict[str, str]],
        recent_messages: list[dict[str, str]] | None = None,
    ) -> list[LLMConversationMessage]:
        normalized: list[LLMConversationMessage] = []
        if recent_messages:
            lines = ["以下是本次触发前，当前群里最近的消息，仅供理解上下文："]
            for index, item in enumerate(recent_messages[-MAX_TRIGGER_CONTEXT_MESSAGES:], 1):
                sender_name = item["sender_name"].strip() or item["user_id"]
                canonical_name = item.get("canonical_name", "").strip()
                user_id = item["user_id"]
                if canonical_name and canonical_name != sender_name:
                    speaker = f"{canonical_name}（QQ {user_id}，当前显示名：{sender_name}）"
                elif canonical_name:
                    speaker = f"{canonical_name}（QQ {user_id}）"
                else:
                    speaker = f"{sender_name}（QQ {user_id}，未登记）"
                lines.append(f"{index}. {speaker}：{item['text']}")
            normalized.append(LLMConversationMessage(role="user", content="\n".join(lines)))

        normalized.extend(
            LLMConversationMessage(role=item["role"], content=item["content"])
            for item in history
            if item["role"] in {"user", "assistant"} and item["content"].strip()
        )
        return normalized

    def _build_messages(
        self,
        *,
        prompt: str,
        image_urls: list[str],
        history: list[dict[str, str]],
        recent_messages: list[dict[str, str]] | None,
    ) -> list[LLMConversationMessage]:
        messages = self._normalize_history(history, recent_messages=recent_messages)
        messages.append(
            LLMConversationMessage(
                role="user",
                content=prompt,
                image_urls=list(image_urls),
            )
        )
        return messages

    async def _run_tool_call_loop(
        self,
        *,
        provider: ProviderConfig,
        request: LLMRequest,
        context: ToolExecutionContext,
    ):
        client = build_provider_client(provider)
        max_rounds = max(0, min(self.config.runtime.tool_max_rounds, 16))
        max_calls = max(1, min(self.config.runtime.tool_max_calls_per_round, 32))
        search_backend = get_search_backend_name()
        search_unlimited = search_backend == "searxng"
        current_request = request
        counted_rounds = 0

        for round_index in range(SEARCH_TOOL_FAILSAFE_MAX_ROUNDS + 1):
            response = await client.complete(current_request)
            logger.info(
                "LLM completion: provider=%s model=%s finish_reason=%s tool_calls=%s round=%s",
                provider.id,
                response.model,
                response.finish_reason,
                len(response.tool_calls),
                round_index,
            )
            if not response.tool_calls or not current_request.allow_tool_calls:
                return response

            search_calls = [call for call in response.tool_calls if call.name == SEARCH_TOOL_NAME]
            other_calls = [call for call in response.tool_calls if call.name != SEARCH_TOOL_NAME]
            has_non_search_calls = bool(other_calls)

            if has_non_search_calls and counted_rounds >= max_rounds:
                response.text = response.text or "工具调用轮次已达上限，未能完成最终回答。"
                return response

            if search_unlimited:
                selected_calls = [
                    *search_calls[:SEARCH_TOOL_FAILSAFE_MAX_CALLS_PER_ROUND],
                    *other_calls[:max_calls],
                ]
            else:
                selected_calls = response.tool_calls[:max_calls]

            if not selected_calls:
                response.text = response.text or "工具调用请求为空，未能完成最终回答。"
                return response

            if has_non_search_calls or not search_unlimited:
                counted_rounds += 1

            if round_index >= SEARCH_TOOL_FAILSAFE_MAX_ROUNDS:
                response.text = response.text or "联网检索轮次过多，已触发安全上限，未能完成最终回答。"
                return response

            assistant_message = LLMConversationMessage(
                role="assistant",
                content=response.text,
                tool_calls=selected_calls,
            )

            logger.info(
                "LLM tool calls requested: provider=%s model=%s names=%s",
                provider.id,
                response.model,
                [call.name for call in selected_calls],
            )
            tool_results = [await self.tool_registry.execute(call, context) for call in selected_calls]
            tool_messages = [
                LLMConversationMessage(
                    role="tool",
                    content=item.content,
                    tool_call_id=item.call_id,
                    tool_name=item.name,
                    is_tool_error=item.is_error,
                )
                for item in tool_results
            ]

            current_request = LLMRequest(
                model=current_request.model,
                system_prompt=current_request.system_prompt,
                messages=[*current_request.messages, assistant_message, *tool_messages],
                temperature=current_request.temperature,
                max_output_tokens=current_request.max_output_tokens,
                tools=current_request.tools,
                allow_tool_calls=current_request.allow_tool_calls,
                tool_choice=current_request.tool_choice,
            )

        raise RuntimeError("工具调用循环未按预期结束")

    async def generate_reply(
        self,
        *,
        group_id: int | str,
        user_id: int | str,
        sender_name: str,
        prompt: str,
        image_urls: list[str] | None = None,
        recent_messages: list[dict[str, str]] | None = None,
    ) -> dict[str, str]:
        prompt = prompt.strip()
        normalized_image_urls = [url for url in (image_urls or []) if url.strip()]
        if not prompt and normalized_image_urls:
            prompt = "请描述这张图片，并优先回答群友最可能想知道的内容。"

        if not prompt:
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

        settings = self.get_group_settings(group_id)
        if not settings.enabled:
            return {
                "reply": "本群 LLM 已关闭。",
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
        history = self.store.list_recent_conversation_messages(
            group_id,
            min(self.config.runtime.history_limit, MAX_CONVERSATION_HISTORY_MESSAGES),
        )
        if self.config.mcp.enabled:
            await self.ensure_mcp_ready()
        memories: list[dict[str, object]] = []
        if settings.memory_enabled:
            memories = self.store.search_memories(
                group_id,
                user_id=user_id,
                query=trimmed_prompt,
                limit=min(self.config.runtime.memory_limit, MAX_MEMORY_RETRIEVAL_ITEMS),
            )

        tool_specs = self._get_enabled_tool_specs() if self.config.runtime.tool_calling_enabled else []
        system_prompt = self._build_system_prompt(
            persona,
            group_id,
            user_id,
            sender_name,
            trimmed_prompt,
            memories,
            tool_specs,
        )
        messages = self._build_messages(
            prompt=trimmed_prompt,
            image_urls=normalized_image_urls,
            history=history,
            recent_messages=recent_messages,
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
            group_id=group_id,
            user_id=user_id,
            sender_name=sender_name,
            provider_id=provider.id,
            model=request.model,
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

        text = re.sub(r"\n{3,}", "\n\n", response.text).strip()
        if not text:
            text = "模型没有返回可显示的文本。"

        self.store.append_conversation_message(group_id, user_id, "user", trimmed_prompt)
        self.store.append_conversation_message(group_id, None, "assistant", text)
        self.store.prune_conversation_messages(
            group_id,
            min(self.config.runtime.history_max_messages_per_group, MAX_STORED_CONVERSATION_MESSAGES),
        )

        return {
            "reply": text,
            "rate_limit_key": LLM_RULE_NAME,
            "rule_name": LLM_RULE_NAME,
        }


llm_service = LLMService()
