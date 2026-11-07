from __future__ import annotations


import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from quickquip.llm.config import LLMConfig, provider_builtin_search_active
from quickquip.llm.image_preprocessor import ImagePreprocessor, VisionImagePreprocessor
from quickquip.llm.provider import build_provider_client
from quickquip.llm.service_parts.constants import (
    ACTIVATE_SKILL_TOOL_NAME,
    DEFAULT_ALWAYS_LOADED_TOOLS,
    DEFAULT_ENABLED_TOOLS,
    MAX_TRIGGER_CONTEXT_MESSAGES,
    PRIVATE_UNAVAILABLE_TOOLS,
    READ_SKILL_RESOURCE_TOOL_NAME,
    RUN_SKILL_SCRIPT_TOOL_NAME,
    SEARCH_TOOL_NAME,
    SEARCH_SKILL_RESOURCES_TOOL_NAME,
    TOOL_LIST_NAME,
    TOOL_SEARCH_NAME,
)
from quickquip.llm.history_tools import (
    HISTORY_TOOLS,
    CONTEXT_NOTE_MAX_CHARS,
    INVESTIGATION_BUDGET_REPLY,
    HistoryToolDeps,
    INVESTIGATE_GROUP_HISTORY_SPEC,
    MAX_ANCHORS,
    MIN_PARENT_REPORT_SPACE,
    QUESTION_MAX_CHARS,
    READ_GROUP_HISTORY_SPEC,
    SEARCH_GROUP_HISTORY_SPEC,
    INVESTIGATION_REPORT_TOKEN_CAP,
    parse_history_time,
    redact_read_arguments,
    redact_recent_arguments,
    redact_search_arguments,
    render_investigation_result,
    run_group_history_read,
    run_group_history_search,
)
from quickquip.llm.service_parts.mcp_lifecycle import McpLifecycleMixin
from quickquip.llm.tool_discovery import resolve_explicit_tool_names
from quickquip.llm.tool_registry import estimate_spec_tokens
from quickquip.llm.tools import LLMToolSpec, ToolExecutionContext
from quickquip.search.web_search import SearXNGSearchClient, format_search_response

if TYPE_CHECKING:
    from quickquip.chat.message_stats import GroupStatsTracker
    from quickquip.chat.rule_switch import GroupRuleSwitch
    from quickquip.common.recent_message_buffer import RecentMessageBuffer

logger = logging.getLogger(__name__)

# 模型可见的身份类工具输出统一附带的路由说明：画图/语音/搜索等能力可能由
# 不同模型通道服务，Provider/Model 字段只描述当前对话的路由，避免模型
# 据此把历史回复归因给虚构的其他"模型人格"。
_MODEL_ROUTING_NOTE = (
    "路由说明：Provider/Model 仅表示当前对话的路由配置；"
    "画图、语音、搜索等其他能力可能由不同模型通道服务，"
    "对话人格始终是同一个机器人。"
)


class ToolMixin(McpLifecycleMixin):
    # MRO contract: ToolMixin calls self._context_scope_key / self.build_chat_scope_key
    # (defined in ScopeMixin) and self._scope_subject / self._memory_label
    # (also ScopeMixin); _register_builtin_tools additionally
    # calls self.register_draw_svg_tool (defined in DrawSvgToolMixin) and
    # self.register_schedule_messages_tool (defined in ScheduleMessagesToolMixin),
    # and reload_runtime calls self.start_mcp_background / self.ensure_mcp_ready.
    # MCP tool names are read via the public ``mcp_tool_names`` accessor —
    # ToolMixin inherits McpLifecycleMixin (which owns the ``_mcp_*`` state)
    # so that narrow interface is available on any host, minimal fakes included.
    # ScopeMixin, DrawSvgToolMixin and ScheduleMessagesToolMixin must precede
    # ToolMixin in the LLMService base list.
    def _register_builtin_tools(self) -> None:
        self.tool_registry.register(
            LLMToolSpec(
                name=TOOL_SEARCH_NAME,
                description="按能力关键词搜索可用工具并在下一轮加载；"
                "query 也支持 select:名称1,名称2 按名精确批量加载"
                "（预期要用多个工具时合并进一次调用，不要逐个加载）。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "category": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            ),
            self._tool_search_tools,
            category="tools",
            keywords=["tool", "tools", "工具", "能力", "mcp", "github", "search"],
            always_loaded=True,
        )
        self.tool_registry.register(
            LLMToolSpec(
                name=TOOL_LIST_NAME,
                description="列出工具组、工具名称或工具摘要，"
                "也可按精确工具名加载少量工具作为 tool_search 的兜底。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["groups", "names", "summaries", "group", "load"],
                        },
                        "group": {"type": "string"},
                        "page": {"type": "integer"},
                        "limit": {"type": "integer"},
                        "names": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["mode"],
                },
            ),
            self._tool_list_tools,
            category="tools",
            keywords=["tool", "tools", "工具", "目录", "列表", "分组", "catalog", "list", "load"],
            always_loaded=True,
        )
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
            category="identity",
            keywords=["身份", "人物", "群友", "别名", "qq"],
            always_loaded=True,
        )
        from quickquip.llm.service_parts.memory_tools import register_memory_tools
        register_memory_tools(self.tool_registry, lambda: self.store,
                              lambda chat_id, chat_type: self.get_chat_settings(chat_id, chat_type),
                              lambda: self.config.runtime.memory_max_items_per_group,
                              lambda name, context: self.config.runtime.tool_calling_enabled
                              and name in self._get_enabled_tool_names(
                                  context.chat_type, provider_id=context.provider_id))
        self.tool_registry.register(
            LLMToolSpec(
                name=SEARCH_TOOL_NAME,
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
            category="search",
            keywords=["联网", "网页", "新闻", "最新", "搜索", "web", "searxng"],
            always_loaded=True,
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
            category="group",
            keywords=["统计", "活跃", "消息数", "群状态"],
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
            category="group",
            keywords=["规则", "开关", "状态"],
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
            category="context",
            keywords=["最近消息", "上下文", "短期缓冲", "群聊记录"],
            # 短期缓冲正文同为群聊临时载荷（ADR-0005）：声明与结果均走
            # 临时保留策略，持久化只留模式事实。
            result_retention="ephemeral",
            redact_arguments=redact_recent_arguments,
        )
        self.tool_registry.register(
            SEARCH_GROUP_HISTORY_SPEC,
            self._tool_search_group_history,
            category="history",
            keywords=["群聊历史", "历史消息", "归档", "搜索记录", "谁说过"],
            result_retention="ephemeral",
            redact_arguments=redact_search_arguments,
        )
        self.tool_registry.register(
            READ_GROUP_HISTORY_SPEC,
            self._tool_read_group_history,
            category="history",
            keywords=["群聊历史", "上下文", "阅读记录", "附近消息"],
            result_retention="ephemeral",
            redact_arguments=redact_read_arguments,
        )
        self.tool_registry.register(
            INVESTIGATE_GROUP_HISTORY_SPEC,
            self._tool_investigate_group_history,
            category="history",
            keywords=["群聊历史", "调查", "时间线", "追查", "多方核对"],
            result_retention="ephemeral",
            redact_arguments=redact_search_arguments,
        )
        self.tool_registry.register(
            LLMToolSpec(
                name="get_llm_status",
                description="查看当前群 LLM 状态与配置，可选返回简版状态或当前详细配置"
                "（provider、model、persona、触发方式等）。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "detail": {"type": "string", "enum": ["status", "current"]},
                    },
                },
            ),
            self._tool_get_llm_status,
            category="diagnostics",
            keywords=["llm", "状态", "配置", "当前", "模型", "provider", "persona", "触发"],
        )
        self.tool_registry.register(
            LLMToolSpec(
                name="get_health_status",
                description="执行一次轻量内部健康检查，覆盖 LLM 配置、当前 provider/model、"
                "资料库、数据库、工具、MCP、搜索和生成配置。"
                "仅在用户明确要求诊断或自检时调用。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "verbose": {"type": "boolean"},
                    },
                },
            ),
            self._tool_get_health_status,
            category="diagnostics",
            keywords=["健康检查", "诊断", "自检", "health"],
        )
        # draw_svg 独立成 DrawSvgToolMixin（tools.py 已超长度预警线）
        self.register_draw_svg_tool()
        # manage_scheduled_messages 独立成 ScheduleMessagesToolMixin（同上）
        self.register_schedule_messages_tool()

    def register_tool(self, spec: LLMToolSpec, handler) -> None:
        self.tool_registry.register(spec, handler)

    # ── tool discovery policy (off / on / auto) ──────────────────────
    # Moved from service.py: these methods decide which tools are visible
    # to the LLM based on the discovery_mode config and chat_type. Called
    # by service.py's prompt builder and tool loop, and by ToolMixin's own
    # _tool_search_tools / _tool_list_tools handlers.

    def _builtin_search_active(self, provider_id: str | None) -> bool:
        """该 provider 会话是否由内置搜索接管联网检索（从而移除 search_web）。"""
        if not provider_id:
            return False
        provider = (
            self.effective_request_provider(provider_id)
            if hasattr(self, "effective_request_provider")
            else self.config.providers.get(provider_id)
        )
        return provider is not None and provider_builtin_search_active(provider)

    def _get_enabled_tool_names(
        self,
        chat_type: str = "group",
        *,
        provider_id: str | None = None,
        history_enabled: bool = False,
    ) -> list[str]:
        configured = self.config.tools.enabled
        if not configured:
            names = [*DEFAULT_ENABLED_TOOLS, *sorted(self.mcp_tool_names)]
        elif self.config.tools.enabled_mode == "replace":
            names = list(configured)
        else:  # append：默认白名单 + MCP 工具之上追加，opt-in 工具的启用路径
            names = [*DEFAULT_ENABLED_TOOLS, *sorted(self.mcp_tool_names), *configured]
        names = list(dict.fromkeys(names))
        if not self.config.skills.enabled:
            skill_tools = {
                ACTIVATE_SKILL_TOOL_NAME, READ_SKILL_RESOURCE_TOOL_NAME,
                SEARCH_SKILL_RESOURCES_TOOL_NAME, RUN_SKILL_SCRIPT_TOOL_NAME,
            }
            names = [name for name in names if name not in skill_tools]
        if chat_type == "private":
            names = [name for name in names if name not in PRIVATE_UNAVAILABLE_TOOLS]
        if not history_enabled:
            # #72：群历史工具只对「全局配置 + 群开关」双开的面曝光；
            # 私聊恒不曝光，handler 内再校验一次（防绕过）。
            names = [name for name in names if name not in HISTORY_TOOLS]
        if self._builtin_search_active(provider_id):
            # 内置搜索开启的 provider 会话移除 search_web，避免模型面前
            # 出现客户端与 provider 原生两条竞争的搜索路径。
            names = [name for name in names if name != SEARCH_TOOL_NAME]
        return [name for name in names if self.tool_registry.has_tool(name)]

    def _get_always_loaded_tool_names(
        self,
        chat_type: str = "group",
        *,
        provider_id: str | None = None,
        history_enabled: bool = False,
    ) -> list[str]:
        configured = self.config.tools.always_loaded or DEFAULT_ALWAYS_LOADED_TOOLS
        enabled = set(self._get_enabled_tool_names(
            chat_type=chat_type, provider_id=provider_id, history_enabled=history_enabled
        ))
        names = [
            name for name in configured if name in enabled and self.tool_registry.has_tool(name)
        ]
        if (
            self._is_tool_discovery_enabled(
                chat_type, provider_id=provider_id, history_enabled=history_enabled
            )
            and TOOL_SEARCH_NAME in enabled
            and TOOL_SEARCH_NAME not in names
        ):
            names.insert(0, TOOL_SEARCH_NAME)
        return names

    def _is_tool_discovery_enabled(
        self,
        chat_type: str = "group",
        *,
        provider_id: str | None = None,
        history_enabled: bool = False,
    ) -> bool:
        mode = self.config.tools.discovery_mode
        if mode == "off":
            return False
        # Cache the enabled-names list once — previously this was recomputed
        # up to 5+ times per call (inside list/set comprehensions), each time
        # rebuilding the filtered list through tool_registry.has_tool().
        enabled = self._get_enabled_tool_names(
            chat_type=chat_type, provider_id=provider_id, history_enabled=history_enabled
        )
        if TOOL_SEARCH_NAME not in enabled:
            return False
        enabled_set = set(enabled)
        configured = self.config.tools.always_loaded or DEFAULT_ALWAYS_LOADED_TOOLS
        always_names = {
            name for name in configured
            if name in enabled_set and self.tool_registry.has_tool(name)
        }
        if mode == "on":
            return len(enabled) > len(always_names)
        deferred_names = enabled_set - always_names
        if len(deferred_names) > self.config.tools.discovery_min_tools:
            return True
        # 体量控线：个数不多但 schema 总量已足以常驻挤占上下文时同样开启
        min_schema_tokens = self.config.tools.discovery_min_schema_tokens
        if min_schema_tokens <= 0 or not deferred_names:
            return False
        deferred_tokens = sum(
            estimate_spec_tokens(spec)
            for spec in self.tool_registry.get_specs(sorted(deferred_names))
        )
        return deferred_tokens > min_schema_tokens

    def _get_enabled_tool_specs(
        self,
        chat_type: str = "group",
        *,
        provider_id: str | None = None,
        history_enabled: bool = False,
    ) -> list[LLMToolSpec]:
        if self._is_tool_discovery_enabled(
            chat_type, provider_id=provider_id, history_enabled=history_enabled
        ):
            return self.tool_registry.get_specs(
                self._get_always_loaded_tool_names(
                    chat_type=chat_type,
                    provider_id=provider_id,
                    history_enabled=history_enabled,
                )
            )
        return self.tool_registry.list_specs(
            self._get_enabled_tool_names(
                chat_type=chat_type,
                provider_id=provider_id,
                history_enabled=history_enabled,
            )
        )

    def _get_deferred_tool_categories(
        self,
        chat_type: str = "group",
        *,
        provider_id: str | None = None,
        history_enabled: bool = False,
    ) -> list[str]:
        if not self._is_tool_discovery_enabled(
            chat_type, provider_id=provider_id, history_enabled=history_enabled
        ):
            return []
        loaded = set(self._get_always_loaded_tool_names(
            chat_type=chat_type, provider_id=provider_id, history_enabled=history_enabled
        ))
        categories: list[str] = []
        for entry in self.tool_registry.list_manifest(
            self._get_enabled_tool_names(
                chat_type=chat_type, provider_id=provider_id, history_enabled=history_enabled
            )
        ):
            if entry.name in loaded:
                continue
            category = entry.category or entry.source
            if category and category not in categories:
                categories.append(category)
        return categories

    def _get_deferred_tool_names(
        self,
        chat_type: str = "group",
        *,
        provider_id: str | None = None,
        history_enabled: bool = False,
    ) -> list[str]:
        """discovery 开启时按名延迟加载的工具清单（信封公告用，仅名字）。"""
        if not self.config.runtime.tool_calling_enabled:
            # 工具总闸关闭时模型面前没有任何工具，公告会诱导无效调用
            # （与 tool_specs 的闸门同口径）。
            return []
        if not self._is_tool_discovery_enabled(
            chat_type, provider_id=provider_id, history_enabled=history_enabled
        ):
            return []
        loaded = set(self._get_always_loaded_tool_names(
            chat_type=chat_type, provider_id=provider_id, history_enabled=history_enabled
        ))
        meta_names = {TOOL_SEARCH_NAME, TOOL_LIST_NAME}
        return [
            name
            for name in self._get_enabled_tool_names(
                chat_type=chat_type, provider_id=provider_id, history_enabled=history_enabled
            )
            if name not in loaded and name not in meta_names
        ]

    def bind_group_stats_tracker(self, tracker: "GroupStatsTracker | None") -> None:
        self.stats_tracker = tracker
        self._identity_repository.names_provider = (
            (lambda gid: getattr(tracker.get_stats(gid), "user_names", {})) if tracker else None
        )

    def bind_rule_switch(self, rule_switch: "GroupRuleSwitch | None") -> None:
        self.rule_switch = rule_switch

    def bind_recent_message_buffer(self, buffer: "RecentMessageBuffer | None") -> None:
        self.recent_message_buffer = buffer

    def bind_group_history(self, query_service) -> None:
        """#72：注入同群只读历史查询服务（app 层 ChatArchive 的门面）。"""
        self.group_history_service = query_service

    def _effective_history_enabled(self, group_id: int | str, chat_type: str) -> bool:
        """群历史双开关仲裁：群级显式开关 > [group_history].enabled；私聊恒关。"""
        if chat_type != "group":
            return False
        override = self.store.get_group_history_flag(group_id) if self.store else None
        return self.config.group_history.enabled if override is None else override

    def _history_deps(self) -> HistoryToolDeps | None:
        service = getattr(self, "group_history_service", None)
        if service is None:
            return None

        def _is_enabled(group_id) -> bool:
            return self._effective_history_enabled(group_id, chat_type="group")

        def _resolve_speaker(group_id, query: str) -> list[str]:
            entries = self._resolve_identities(str(group_id)).search(query, limit=5)
            qq_ids: list[str] = []
            for entry in entries:
                for qq in entry.qq_ids:
                    if qq not in qq_ids:
                        qq_ids.append(qq)
            return qq_ids

        return HistoryToolDeps(
            query_service=service,
            is_enabled=_is_enabled,
            resolve_speaker=_resolve_speaker,
        )

    async def _tool_search_group_history(
        self, arguments: dict[str, object], context: ToolExecutionContext
    ) -> str:
        deps = self._history_deps()
        if deps is None:
            return "群聊历史查询未启用。"
        return await run_group_history_search(deps, arguments, context)

    async def _tool_read_group_history(
        self, arguments: dict[str, object], context: ToolExecutionContext
    ) -> str:
        deps = self._history_deps()
        if deps is None:
            return "群聊历史查询未启用。"
        return await run_group_history_read(deps, arguments, context)

    def _resolve_investigation_model(self, context: ToolExecutionContext):
        """调查执行器模型解析：专用覆盖 > 父请求路由；无效覆盖显式报错。

        返回 (provider, model) 或错误字符串。
        """
        from quickquip.llm.config_document import resolve_model_provider

        overrides = self.config.group_history
        provider_id = overrides.investigation_provider_id or context.provider_id
        provider = self.config.providers.get(provider_id)
        if provider is None:
            return f"调查渠道配置无效：provider {provider_id} 不存在"
        if overrides.investigation_model:
            model = overrides.investigation_model
        elif provider_id == context.provider_id:
            model = context.model
        else:
            model = provider.default_model
        try:
            return resolve_model_provider(self.config, provider_id, model)
        except ValueError:
            return (
                f"调查模型配置无效：{provider_id}/{model} 不可用"
                "（不存在或已停用），请修正 [group_history] 配置"
            )

    async def _tool_investigate_group_history(
        self, arguments: dict[str, object], context: ToolExecutionContext
    ) -> str:
        from quickquip.llm.history_investigation import (
            InvestigationLimits,
            InvestigationTask,
            run_history_investigation,
        )
        from quickquip.llm.token_estimate import estimate_tokens

        if context.chat_type != "group":
            return "该工具仅支持群聊使用。"
        if not self._effective_history_enabled(context.group_id, context.chat_type):
            return "本群未开启群聊历史查询，无法执行。"
        state = getattr(context, "history", None)
        if state is None or self.group_history_service is None:
            return "群聊历史查询未启用。"

        # 父 Loop 最多委派一次；重复调用返回既有当轮结果
        if state.investigation_used:
            return (
                state.investigation_result_text
                + "\n（本回答周期已委派过一次调查，以上为既有结果。）"
            )
        if state.allowance(INVESTIGATION_REPORT_TOKEN_CAP, 0) < MIN_PARENT_REPORT_SPACE:
            return INVESTIGATION_BUDGET_REPLY

        question = str(arguments.get("question", "")).strip()[:QUESTION_MAX_CHARS]
        if not question:
            return "缺少调查问题：question 必须写清要查证什么。"
        task = InvestigationTask(
            question=question,
            context_note=str(arguments.get("context", "") or "").strip()[
                :CONTEXT_NOTE_MAX_CHARS
            ],
            anchors=[
                str(a).strip()
                for a in (arguments.get("anchors") or [])[:MAX_ANCHORS]
                if str(a).strip()
            ],
        )
        for key, target in (("start", "start_ts"), ("end", "end_ts")):
            raw = arguments.get(key)
            if raw:
                parsed = parse_history_time(str(raw))
                if parsed is None:
                    return "时间格式无法解析：请用 YYYY-MM-DD 或 ISO 8601（北京时间）。"
                setattr(task, target, parsed.timestamp())

        resolved = self._resolve_investigation_model(context)
        if isinstance(resolved, str):
            return resolved
        provider, model = resolved

        settings = self.config.group_history
        limits = InvestigationLimits(
            timeout_seconds=settings.investigation_timeout_seconds,
            max_model_calls=settings.investigation_max_calls,
            max_tool_calls=settings.investigation_max_calls * 2,
        )
        result = await run_history_investigation(
            task=task,
            provider=provider,
            model=model,
            runtime_config=self.config.runtime,
            query_service=self.group_history_service,
            group_id=context.group_id,
            parent_scope_key=context.chat_scope or str(context.group_id),
            build_provider_client=build_provider_client,
            limits=limits,
            parent_cancel_check=state.parent_cancel_check,
        )
        text = render_investigation_result(result, INVESTIGATION_REPORT_TOKEN_CAP)
        state.consume(estimate_tokens(text))
        state.investigation_used = True
        state.investigation_result_text = text
        return text

    def bind_image_preprocessor(self, preprocessor: ImagePreprocessor | None) -> None:
        self.image_preprocessor = preprocessor

    def rebuild_image_preprocessor(self) -> None:
        img_cfg = self.config.image_preprocessing
        if not img_cfg.enabled or not img_cfg.provider_id:
            self.image_preprocessor = None
            return

        vis_provider_cfg = self.config.providers.get(img_cfg.provider_id)
        if vis_provider_cfg is None:
            logger.warning(
                "image_preprocessing.provider_id %r not found in providers",
                img_cfg.provider_id,
            )
            self.image_preprocessor = None
            return

        vision_model = img_cfg.model or vis_provider_cfg.default_model
        from quickquip.llm.config_document import resolve_model_provider
        try:
            vis_provider_cfg = resolve_model_provider(
                self.config, vis_provider_cfg.id, vision_model
            )
        except ValueError:
            self.image_preprocessor = None
            return
        if vision_model in vis_provider_cfg.non_vision_models:
            logger.warning(
                "image_preprocessing model %r is declared non-vision by provider %r",
                vision_model,
                img_cfg.provider_id,
            )
            self.image_preprocessor = None
            return

        vis_client = build_provider_client(replace(vis_provider_cfg, stream_enabled=False))
        self.image_preprocessor = VisionImagePreprocessor(
            provider_client=vis_client,
            model=vision_model,
            max_tokens=img_cfg.max_tokens,
            temperature=img_cfg.temperature,
            prompt=img_cfg.prompt,
        )

    async def reload_runtime(self, *, background: bool = False) -> LLMConfig:
        async with self._configuration_gate:
            self.reload_config()
        await self.reload_mcp(background=background)
        return self.config

    async def _tool_get_identity(
        self, arguments: dict[str, object], context: ToolExecutionContext
    ) -> str:
        query = str(arguments.get("query", "")).strip()
        matches = self._resolve_identities(str(context.group_id)).search(query, limit=5)
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

    async def _tool_search_tools(
        self, arguments: dict[str, object], context: ToolExecutionContext
    ) -> str:
        query = str(arguments.get("query", "")).strip()
        category = str(arguments.get("category", "")).strip()
        raw_limit = arguments.get("limit", self.config.tools.discovery_search_limit)
        try:
            limit = int(raw_limit or self.config.tools.discovery_search_limit)
        except (TypeError, ValueError):
            limit = self.config.tools.discovery_search_limit
        limit = max(1, min(limit, self.config.tools.discovery_search_limit))
        current_enabled = self._get_enabled_tool_names(
            chat_type=context.chat_type, provider_id=context.provider_id
        )
        loaded_names = set(
            self._get_always_loaded_tool_names(
                chat_type=context.chat_type, provider_id=context.provider_id
            )
        )

        explicit = resolve_explicit_tool_names(query, current_enabled)
        if explicit is not None:
            # select:/裸名点名：可用（常驻或下一轮加载）与未找到分组回报；
            # 点名已可用工具是无害 no-op，不构成错误（防模型重试打转）。
            enabled_set = set(current_enabled)
            available: list[str] = []
            missing: list[str] = []
            for name in explicit:
                if name in enabled_set and self.tool_registry.has_tool(name):
                    available.append(name)
                else:
                    missing.append(name)
            lines = ["工具加载请求："]
            if available:
                lines.append(
                    "- "
                    + "、".join(
                        f"{name}（{'已常驻' if name in loaded_names else '将于下一轮可用'}）"
                        for name in available
                    )
                )
            if missing:
                lines.append(f"- 未找到：{'、'.join(missing)}（可用 tool_list 查看工具目录）")
            lines.append("下一轮请直接调用已加载的工具名。")
            return "\n".join(lines)
        matches = self.tool_registry.search_manifest(
            query,
            enabled_names=current_enabled,
            exclude_names=[TOOL_SEARCH_NAME],
            category=category,
            limit=limit,
        )
        if not matches:
            suffix = f"（类别：{category}）" if category else ""
            return f"没有找到与“{query}”匹配的可用工具{suffix}。"

        lines = ["工具搜索结果："]
        for item in matches:
            state = "已常驻" if item.name in loaded_names else "将于下一轮可用"
            args = f"；参数：{', '.join(item.argument_names)}" if item.argument_names else ""
            category_part = f"；类别：{item.category}" if item.category else ""
            lines.append(f"- {item.name}（{state}{category_part}{args}）：{item.description}")
        lines.append("如需使用其中某个工具，请在下一轮直接调用对应工具名。")
        return "\n".join(lines)

    async def _tool_list_tools(
        self, arguments: dict[str, object], context: ToolExecutionContext
    ) -> str:
        mode = str(arguments.get("mode", "")).strip().lower()
        group = str(arguments.get("group", "")).strip()
        try:
            page = int(arguments.get("page", 1) or 1)
        except (TypeError, ValueError):
            page = 1
        try:
            limit = int(arguments.get("limit", 20) or 20)
        except (TypeError, ValueError):
            limit = 20
        page = max(1, page)
        limit = max(1, min(limit, 50))
        enabled_names = self._get_enabled_tool_names(
            chat_type=context.chat_type, provider_id=context.provider_id
        )

        if mode == "groups":
            groups = self.tool_registry.list_groups(enabled_names)
            if not groups:
                return "当前没有可用工具组。"
            lines = ["工具组列表："]
            for item in groups:
                samples = "、".join(item["sample_tools"])
                suffix = f"；示例：{samples}" if samples else ""
                lines.append(f"- {item['name']}：{item['tool_count']} 个工具{suffix}")
            lines.append("可用 tool_list mode=\"group\" 并传入 group 查看某组工具。")
            return "\n".join(lines)

        if mode in {"names", "summaries", "group"}:
            entries, total = self.tool_registry.list_manifest_page(
                enabled_names=enabled_names,
                group=group,
                page=page,
                limit=limit,
            )
            group_part = f"（组：{group}）" if group else ""
            if not entries:
                return f"没有找到可列出的工具{group_part}。"
            header_mode = "工具摘要" if mode in {"summaries", "group"} else "工具名称"
            start = (page - 1) * limit + 1
            end = start + len(entries) - 1
            lines = [f"{header_mode}{group_part}：第 {page} 页，{start}-{end}/{total}"]
            for item in entries:
                if mode in {"summaries", "group"}:
                    args = (
                        f"；参数：{', '.join(item.argument_names)}"
                        if item.argument_names
                        else ""
                    )
                    category = f"；组：{item.category}" if item.category else ""
                    lines.append(f"- {item.name}{category}{args}：{item.description}")
                else:
                    lines.append(f"- {item.name}")
            if end < total:
                lines.append(f"还有更多工具，可用 page={page + 1} 继续查看。")
            if mode != "names":
                lines.append("如需加载某些工具，可用 tool_list mode=\"load\" 并传入 names。")
            return "\n".join(lines)

        if mode == "load":
            raw_names = arguments.get("names", [])
            if not isinstance(raw_names, list):
                return "names 必须是工具名数组。"
            requested = [str(name).strip() for name in raw_names if str(name).strip()]
            if not requested:
                return "请在 names 中提供要加载的工具名。"
            enabled_set = set(enabled_names)
            valid = [
                name for name in requested[: self.config.tools.discovery_search_limit]
                if name in enabled_set and self.tool_registry.has_tool(name)
            ]
            invalid = [name for name in requested if name not in valid]
            lines = ["工具加载请求："]
            if valid:
                lines.append(f"- 将于下一轮可用：{', '.join(valid)}")
            if invalid:
                lines.append(f"- 未加载（不存在或未启用）：{', '.join(invalid)}")
            lines.append("下一轮请直接调用已加载的工具名。")
            return "\n".join(lines)

        return "未知 mode。可用 mode：groups、names、summaries、group、load。"

    async def _tool_search_web(
        self, arguments: dict[str, object], context: ToolExecutionContext
    ) -> str:
        _ = context
        query = str(arguments.get("query", "")).strip()
        topic = str(arguments.get("topic", "general")).strip() or "general"
        response = await SearXNGSearchClient().search(query, topic=topic, max_results=5)
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
            top_users = sorted(
                stats.user_messages.items(), key=lambda item: (-item[1], item[0])
            )[:top_n]
            lines.append(f"- 活跃用户 Top {len(top_users)}：")
            for rank, (user_id, count) in enumerate(top_users, 1):
                display_name = stats.user_names.get(user_id, user_id)
                lines.append(f"  {rank}. {display_name}（QQ {user_id}）— {count} 条")
        if stats.rule_triggers:
            top_rules = sorted(
                stats.rule_triggers.items(), key=lambda item: (-item[1], item[0])
            )[:top_n]
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
            text = self.format_current(context.group_id, chat_type=context.chat_type)
        else:
            text = self.format_status(context.group_id, chat_type=context.chat_type)
        return f"{text}\n{_MODEL_ROUTING_NOTE}"

    async def _tool_get_health_status(
        self,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> str:
        verbose = bool(arguments.get("verbose", False))
        return await self.format_health(
            context.group_id, chat_type=context.chat_type, verbose=verbose
        )
