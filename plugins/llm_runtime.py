from __future__ import annotations

import logging
from pathlib import Path
import re
import asyncio

from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.chat.message_stats import GroupStatsTracker
from quickquip.chat.rule_switch import GroupRuleSwitch, SWITCHABLE_RULES
from quickquip.llm.config import LLMConfig, PersonaConfig, ProviderConfig, load_llm_config
from quickquip.llm.identity import IdentityIndex
from quickquip.llm.mcp import MCPClientManager, MCPServerStatus
from quickquip.llm.prompting import (
    build_messages,
    build_system_prompt,
    build_user_message_content,
    format_quoted_speaker,
    merge_image_urls,
    normalize_history,
)
from quickquip.llm.provider import LLMProviderError, LLMRequest, build_provider_client
from quickquip.common.recent_message_buffer import RecentMessageBuffer
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
MAX_QUOTED_MESSAGE_CHARS = 1200
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
        return resolve_group_settings(self.store, self.config, group_id)

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
        )

    def _normalize_history(
        self,
        history: list[dict[str, str]],
        recent_messages: list[dict[str, str]] | None = None,
    ) -> list[LLMConversationMessage]:
        return normalize_history(
            history,
            recent_messages=recent_messages,
            max_trigger_context_messages=MAX_TRIGGER_CONTEXT_MESSAGES,
        )

    def _merge_image_urls(self, *collections: list[str]) -> list[str]:
        return merge_image_urls(*collections)

    def _format_quoted_speaker(self, sender_name: str, user_id: str) -> str:
        return format_quoted_speaker(sender_name, user_id)

    def _build_user_message_content(
        self,
        *,
        prompt: str,
        quoted_text: str = "",
        quoted_sender_name: str = "",
        quoted_user_id: str = "",
        quoted_image_urls: list[str] | None = None,
    ) -> str:
        return build_user_message_content(
            prompt=prompt,
            quoted_text=quoted_text,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
            quoted_image_urls=quoted_image_urls,
            max_quoted_message_chars=MAX_QUOTED_MESSAGE_CHARS,
        )

    def _build_messages(
        self,
        *,
        prompt: str,
        image_urls: list[str],
        history: list[dict[str, str]],
        recent_messages: list[dict[str, str]] | None,
    ) -> list[LLMConversationMessage]:
        return build_messages(
            prompt=prompt,
            image_urls=image_urls,
            history=history,
            recent_messages=recent_messages,
            max_trigger_context_messages=MAX_TRIGGER_CONTEXT_MESSAGES,
        )

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
        )[: self.config.runtime.max_prompt_chars]
        effective_image_urls = self._merge_image_urls(normalized_image_urls, normalized_quoted_image_urls)
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
                query=analysis_prompt or trimmed_prompt,
                limit=min(self.config.runtime.memory_limit, MAX_MEMORY_RETRIEVAL_ITEMS),
            )

        tool_specs = self._get_enabled_tool_specs() if self.config.runtime.tool_calling_enabled else []
        system_prompt = self._build_system_prompt(
            persona,
            group_id,
            user_id,
            sender_name,
            analysis_prompt or trimmed_prompt,
            memories,
            tool_specs,
        )
        messages = self._build_messages(
            prompt=effective_prompt,
            image_urls=effective_image_urls,
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

        self.store.append_conversation_message(group_id, user_id, "user", effective_prompt)
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
