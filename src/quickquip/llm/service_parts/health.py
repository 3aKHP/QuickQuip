from __future__ import annotations

import json

from quickquip.common.paths import MCP_STATUS_JSON_PATH
from quickquip.common.sensitive_filter import get_filter as _get_sensitive_filter
from quickquip.llm.config import (
    DISABLED_PROVIDER_REPLY,
    REASONING_EFFORT_CHOICES,
    PersonaConfig,
    ProviderConfig,
)
from quickquip.llm.health import HealthReport
from quickquip.llm.health import build_health_report, format_health_report
from quickquip.llm.provider.openai_responses.profiles import resolve_profile
from quickquip.llm.provider.openai_responses.request import reasoning_control
from quickquip.llm.provider_health import format_probe_results, probe_all_providers, probe_provider
from quickquip.llm.settings import ResolvedGroupSettings
from quickquip.llm.thinking import family_defaults_to_max_thinking, resolve_thinking
from quickquip.llm.mcp.types import (
    MCP_FAILURE_AUTH,
    MCP_FAILURE_CONFIG,
    MCP_FAILURE_LEGACY_HANDSHAKE,
    MCP_FAILURE_MODERN_NEGOTIATION,
    MCP_FAILURE_PROBE,
    MCP_FAILURE_ROUTING,
    MCP_FAILURE_TIMEOUT,
    MCP_FAILURE_TRANSPORT,
    MCPServerStatus,
    format_mcp_era_tag,
)
from quickquip.llm.service_parts.constants import (
    MAX_STORED_MEMORY_ITEMS,
    MAX_TRIGGER_CONTEXT_MESSAGES,
)


_MCP_FAILURE_LABELS = {
    MCP_FAILURE_CONFIG: "配置错误",
    MCP_FAILURE_PROBE: "探活失败",
    MCP_FAILURE_LEGACY_HANDSHAKE: "协议握手失败",
    MCP_FAILURE_MODERN_NEGOTIATION: "协议协商失败",
    MCP_FAILURE_AUTH: "认证失败",
    MCP_FAILURE_TIMEOUT: "连接超时",
    MCP_FAILURE_ROUTING: "路由错误",
    MCP_FAILURE_TRANSPORT: "传输错误",
}

_MCP_FAILURE_FALLBACK_LABEL = "连接失败"


class HealthMixin:
    # MRO contract: HealthMixin calls self._get_enabled_tool_names (ToolMixin),
    # self.build_chat_scope_key / self._scope_label
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

    def format_mcp_status(self, *, verbose: bool = False) -> str:
        """Render MCP status. Non-verbose (chat) output only shows the
        failure category derived from failure_kind; verbose (admin surface)
        additionally renders the sanitized raw error text."""
        lines = ["MCP 状态"]
        if not self.config.mcp.enabled:
            lines.append("总开关：OFF")
            return "\n".join(lines)

        lines.append("总开关：ON")
        if self.is_mcp_initializing():
            lines.append("运行态：初始化中")
        shared = self._get_shared_mcp_health()
        if shared is not None and self.is_mcp_dirty():
            summary, _tool_count = shared
            lines.append(f"运行态：{summary}")
            return "\n".join(lines)
        if self.is_mcp_dirty() and not self._get_mcp_statuses():
            lines.append("运行态：待初始化")
            return "\n".join(lines)

        statuses = self._get_mcp_statuses()
        if not statuses:
            lines.append("当前没有已配置的 MCP servers")
            return "\n".join(lines)

        connected = sum(1 for item in statuses if item.connected)
        lines.append(f"连接数：{connected}/{len(statuses)}")
        lines.append(f"工具数：{len(self.mcp_tool_names)}")
        for status in statuses:
            state = "ON" if status.connected else ("OFF" if not status.enabled else "ERROR")
            era_tag = format_mcp_era_tag(status.negotiation, status.era)
            error_part = ""
            if status.error:
                if verbose:
                    error_part = f" error={status.error}"
                else:
                    # Chat surface: server-controlled error text stays out;
                    # only the failure category is shown.
                    label = _MCP_FAILURE_LABELS.get(
                        status.failure_kind, _MCP_FAILURE_FALLBACK_LABEL
                    )
                    error_part = f" error={label}"
            lines.append(
                f"- {status.id} [{status.transport}{era_tag}] {state} tools={status.tool_count}"
                + (f" server={status.server_identity}" if status.server_identity else "")
                + error_part
            )
        return "\n".join(lines)

    def _summarize_mcp_status(self) -> str:
        if not self.config.mcp.enabled:
            return "OFF"
        if self.is_mcp_initializing():
            return "初始化中"
        statuses = self._get_mcp_statuses()
        shared = self._get_shared_mcp_health()
        if shared is not None and self.is_mcp_dirty():
            return shared[0]
        if self.is_mcp_dirty() and not statuses:
            return "待初始化"
        if not statuses:
            return "ON (0/0)"
        connected = sum(1 for item in statuses if item.connected)
        return f"ON ({connected}/{len(statuses)}，{len(self.mcp_tool_names)} tools)"

    def list_providers(self) -> list[ProviderConfig]:
        return [p for p in self.config.providers.values() if p.enabled]

    def list_personas(self, chat_type: str = "group") -> list[PersonaConfig]:
        return [p for p in self.config.personas.values() if not p.scope or chat_type in p.scope]

    def _format_effort_status(
        self, settings: ResolvedGroupSettings, chat_type: str = "group"
    ) -> str:
        """思考档位状态：结果先行一句话，随后说明来源与未生效/自动调整原因。"""
        provider = self.config.providers.get(settings.provider_id)
        scope = "私聊" if chat_type == "private" else "本群"
        override = settings.reasoning_effort_override
        requested = settings.reasoning_effort
        model = settings.model or (provider.default_model if provider else "")
        label = model or "模型"
        if provider is None:
            note = "当前渠道配置缺失（可能已删除或改名）"
            if override:
                note += f"；{scope}设置为 {override}"
            return f"思考档位：无法解析。{note}。"
        if not requested:
            result = f"{label} 自身默认档"
            if family_defaults_to_max_thinking(model):
                result += "（即最高档）"
            return f"思考档位：{result}。{scope}未单独设置。"
        if requested not in REASONING_EFFORT_CHOICES:
            return f"思考档位：{requested}。该档位无法识别，请检查配置。"
        # 请求档来源与常规说明（无调整时只交代出处）
        origin = f"{scope}设置" if override else "渠道配置"
        note = f"来自{origin}" if override else f"来自渠道配置，{scope}未单独设置"
        if provider.protocol == "openai_responses":
            # responses 协议的归一化层在 profile 词表（reasoning_control）。
            control = reasoning_control(
                provider, resolve_profile(provider.responses_profile), tier=requested
            )
            wire = (control or {}).get("effort") or requested
            if wire != requested:
                return (
                    f"思考档位：{wire}。{origin}为 {requested}，"
                    f"该后端不支持该档位，已自动调整。"
                )
            return f"思考档位：{wire}。{note}。"
        directive = resolve_thinking(
            requested,
            provider,
            model,
            max_output_tokens=provider.max_output_tokens,
        )
        if directive is None:
            # 仅 claude budget 数学下限（max_output_tokens ≤1024）一种不发送场景。
            result = f"{label} 自身默认档"
            if family_defaults_to_max_thinking(model):
                result += "（即最高档）"
            return (
                f"思考档位：{result}。{origin}的 {requested} 未能生效："
                f"max_output_tokens 过小，思考预算无法达到 1024 tokens 的下限。"
            )
        if directive.clamped and directive.effort:
            return (
                f"思考档位：{directive.effort}。{origin}为 {requested}，"
                f"该后端不支持该档位，已自动调整。"
            )
        if directive.clamped:
            # claude_budget 受 max_output_tokens 限制；gemini_budget 受模型上限限制
            reason = (
                "受 max_output_tokens 限制"
                if directive.kind == "claude_budget"
                else "受模型上限限制"
            )
            return (
                f"思考档位：{requested}（思考预算 {directive.budget_tokens} tokens）。"
                f"{note}，{reason}。"
            )
        if directive.effort:
            return f"思考档位：{directive.effort}。{note}。"
        return (
            f"思考档位：{requested}（思考预算 {directive.budget_tokens} tokens）。"
            f"{note}。"
        )

    def format_effort_status(self, chat_id: int | str, chat_type: str = "group") -> str:
        return self._format_effort_status(
            self.get_chat_settings(chat_id, chat_type=chat_type), chat_type=chat_type
        )

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
        lines.append(self._format_effort_status(settings, chat_type=chat_type))
        lines.append(f"Persona：{settings.persona_id}")
        lines.append(
            f"前缀触发：{'ON' if settings.allow_prefix else 'OFF'} "
            f"({settings.trigger_prefix})"
        )
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
        if settings.history_limit is not None:
            # 显式 /llm context_limit 覆盖 = 行数兜底滚动窗；默认 = 会话纪元自动管理
            window_note = f"行数兜底 {settings.history_limit} 条（会话覆盖）"
        else:
            window_note = "会话纪元自动管理"
        lines.append(f"总开关：{'ON' if settings.enabled else 'OFF'}")
        lines.append(f"当前会话：{self._scope_label(chat_type)}")
        lines.append(f"记忆注入：{'ON' if settings.memory_enabled else 'OFF'}")
        lines.append(f"工具调用：{'ON' if self.config.runtime.tool_calling_enabled else 'OFF'}")
        lines.append(f"MCP：{self._summarize_mcp_status()}")
        enabled_tool_names = self._get_enabled_tool_names(
            chat_type=chat_type, provider_id=settings.provider_id
        )
        lines.append(f"工具列表：{', '.join(enabled_tool_names) or '无'}")
        lines.append(f"Provider：{settings.provider_id}")
        lines.append(f"Model：{settings.model}")
        lines.append(self._format_effort_status(settings, chat_type=chat_type))
        lines.append(f"Persona：{settings.persona_id}")
        lines.append(
            f"前缀触发：{'ON' if settings.allow_prefix else 'OFF'} "
            f"({settings.trigger_prefix})"
        )
        if chat_type == "private":
            lines.append(f"会话状态：{'进行中' if settings.enabled else '未开启'}")
            lines.append("直聊触发：仅在会话开启后生效")
            lines.append("艾特触发：OFF（私聊不适用）")
        else:
            lines.append(f"艾特触发：{'ON' if settings.allow_at else 'OFF'}")
        lines.append(
            f"短期会话：已存 {self.store.count_conversation_messages(scope_key)} 条 / {window_note}"
        )
        lines.append(
            f"长期记忆：已存 {self.store.count_memories(scope_key)} 条 "
            f"/ 上限 {MAX_STORED_MEMORY_ITEMS} 条"
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
            tool_names=self._get_enabled_tool_names(
                chat_type=chat_type, provider_id=settings.provider_id
            ),
            mcp_status_summary=self._summarize_mcp_status(),
            mcp_enabled=self.config.mcp.enabled,
            mcp_tool_count=(self._get_shared_mcp_health() or ("", len(self.mcp_tool_names)))[1],
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

    async def format_provider_probe(self) -> str:
        """并发探活所有 provider 并格式化结果（/llm probe 用，每次调用即每次计费）。"""
        results = await probe_all_providers(self.config)
        return format_probe_results(results)

    async def format_current_provider_probe(
        self, group_id: int | str, chat_type: str = "group"
    ) -> str:
        """探活当前会话实际生效的 provider/model（/llm reload 后验证用）。"""
        settings = self.get_chat_settings(group_id, chat_type=chat_type)
        provider = self.config.providers.get(settings.provider_id)
        if provider is None:
            return f"当前 provider 不存在：{settings.provider_id}"
        if not provider.enabled:
            return DISABLED_PROVIDER_REPLY.format(provider_id=settings.provider_id)
        result = await probe_provider(provider, model=settings.model or None)
        body = format_probe_results([result])
        if result.status == "ok":
            return body
        return f"配置已生效，但当前 provider 探活未通过：\n{body}"
