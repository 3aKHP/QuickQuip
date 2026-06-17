from __future__ import annotations

import json

from quickquip.common.paths import MCP_STATUS_JSON_PATH
from quickquip.common.sensitive_filter import get_filter as _get_sensitive_filter
from quickquip.llm.config import PersonaConfig, ProviderConfig
from quickquip.llm.health import HealthReport
from quickquip.llm.health import build_health_report, format_health_report
from quickquip.llm.mcp import MCPServerStatus
from quickquip.llm.service_parts.constants import (
    MAX_STORED_MEMORY_ITEMS,
    MAX_TRIGGER_CONTEXT_MESSAGES,
)


class HealthMixin:
    # MRO contract: HealthMixin calls self._get_enabled_tool_names (ToolMixin),
    # self.build_chat_scope_key / self._default_history_limit / self._scope_label
    # (ScopeMixin), and self._auto_memory_* (AutoMemoryMixin). All three must
    # precede HealthMixin in the LLMService base list.
    def _get_mcp_statuses(self) -> list[MCPServerStatus]:
        return self.mcp_manager.get_statuses()

    def _get_shared_mcp_health(self) -> tuple[str, int] | None:
        if not self.config.mcp.enabled or self._get_mcp_statuses():
            return None
        try:
            data = json.loads(MCP_STATUS_JSON_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None

        raw_statuses = data.get("statuses", [])
        if not isinstance(raw_statuses, list) or not raw_statuses:
            return None
        statuses = [item for item in raw_statuses if isinstance(item, dict)]
        if not statuses:
            return None
        connected = sum(1 for item in statuses if item.get("connected"))
        tool_count = 0
        for item in statuses:
            try:
                tool_count += int(item.get("tool_count") or 0)
            except (TypeError, ValueError):
                pass
        return f"ON ({connected}/{len(statuses)}，{tool_count} tools，bot runtime)", tool_count

    def format_mcp_status(self) -> str:
        lines = ["MCP 状态"]
        if not self.config.mcp.enabled:
            lines.append("总开关：OFF")
            return "\n".join(lines)

        lines.append("总开关：ON")
        if self._is_mcp_initializing():
            lines.append("运行态：初始化中")
        shared = self._get_shared_mcp_health()
        if shared is not None and self._mcp_dirty:
            summary, _tool_count = shared
            lines.append(f"运行态：{summary}")
            return "\n".join(lines)
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
        shared = self._get_shared_mcp_health()
        if shared is not None and self._mcp_dirty:
            return shared[0]
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

    async def build_health_report(
        self, group_id: int | str, chat_type: str = "group", *, probe_provider: bool = False
    ) -> HealthReport:
        settings = self.get_chat_settings(group_id, chat_type=chat_type)
        scope_key = self.build_chat_scope_key(group_id, chat_type)
        return await build_health_report(
            config=self.config,
            settings=settings,
            scope_key=scope_key,
            chat_type=chat_type,
            db_path=self.store.path,
            vocab_path=self.vocab_path,
            identity_path=self.identity_path,
            tool_names=self._get_enabled_tool_names(chat_type=chat_type),
            mcp_status_summary=self._summarize_mcp_status(),
            mcp_enabled=self.config.mcp.enabled,
            mcp_tool_count=(self._get_shared_mcp_health() or ("", len(self._mcp_tool_names)))[1],
            recent_buffer_bound=self.recent_message_buffer is not None,
            stats_bound=self.stats_tracker is not None,
            rule_switch_bound=self.rule_switch is not None,
            probe_provider=probe_provider,
            auto_memory_stats={
                # _auto_memory_* attributes are initialised by AutoMemoryMixin._init_auto_memory();
                # AutoMemoryMixin must be in the MRO and _init_auto_memory() called in __init__.
                "successes": self._auto_memory_successes,
                "failures": self._auto_memory_failures,
                "active_scopes": len(self._auto_memory_turns),
            },
            image_preprocessor_bound=self.image_preprocessor is not None,
            sensitive_filter=_get_sensitive_filter(),
        )

    async def format_health(
        self,
        group_id: int | str,
        chat_type: str = "group",
        *,
        verbose: bool = False,
    ) -> str:
        return format_health_report(
            await self.build_health_report(group_id, chat_type=chat_type, probe_provider=verbose),
            verbose=verbose,
        )
