"""Skill 系统工具缝：4 个模型工具的注册、惰性注册与 handler。

从 tools.py 拆出的独立 mixin——后者已超文件长度预警线，新工具不再堆入
（draw_svg 先例）。MRO 契约：本 mixin 依赖宿主（LLMService）的
``tool_registry`` / ``config`` 属性与 ScopeMixin 的 ``_context_scope_key`` /
``build_chat_scope_key`` 方法。

空目录短路（默认零扰动）：``[skills].enabled = false`` 或扫描为空时不
注册工具、catalog 块不渲染；catalog 每轮请求现扫一次（service.py 在
tool specs 计算前调 ``prepare_skill_catalog_for_turn``，渲染块与当轮
specs 出自同一次扫描），首次扫到非空即惰性注册工具（热部署，无 reload
钩子，新 skill 当轮即进 spec 广告面）；此后目录变空则块消失、handler
fail-closed 返回"未安装"文本（不抛异常）。
"""

from __future__ import annotations

import logging

from quickquip.common.sensitive_filter import (
    get_filter as _get_sensitive_filter,
    log_hits as _log_sensitive_hits,
)
from quickquip.llm.context_windows import resolve_context_window
from quickquip.llm.skills import (
    ACTIVATE_SKILL_TOOL_KEYWORDS,
    ACTIVATION_STATUS_ACTIVATED,
    READ_SKILL_RESOURCE_SPEC,
    READ_SKILL_RESOURCE_TOOL_KEYWORDS,
    RUN_SKILL_SCRIPT_SPEC,
    RUN_SKILL_SCRIPT_TOOL_KEYWORDS,
    SEARCH_SKILL_RESOURCES_SPEC,
    SEARCH_SKILL_RESOURCES_TOOL_KEYWORDS,
    LoadedSkill,
    SkillCatalog,
    activate_skill,
    build_activate_skill_spec,
    build_catalog,
    derive_catalog_budget_bytes,
    format_activation_block,
    read_skill_resource,
    render_catalog_block,
    render_skill_list,
    resolve_catalog_dir,
    run_skill_script,
    scan_skills,
    search_skill_resources,
)
from quickquip.llm.skills import SkillActivationState
from quickquip.llm.tools import LLMToolOutput, ToolExecutionContext

logger = logging.getLogger(__name__)


class SkillsToolMixin:
    def _init_skills(self) -> None:
        self._skill_activations = SkillActivationState()
        self._skill_tools_registered = False
        self._skill_registered_names: list[str] = []
        # 当轮扫描的 host 侧映射；空目录/未扫描时为空，handler fail-closed。
        self._skills_catalog_by_name = {}

    # ── 注册 ────────────────────────────────────────────────────

    def register_skill_tools(self) -> None:
        """启动路径：配置启用且目录非空时注册 4 个工具；空目录留待惰性注册。"""
        if not self.config.skills.enabled:
            return
        catalog = self._scan_skill_catalog(context_window_tokens=None)
        self._skills_catalog_by_name = catalog.by_name
        if catalog.entries:
            self._register_skill_tools(catalog.names)

    def _register_skill_tools(self, names: list[str]) -> None:
        self.tool_registry.register(
            build_activate_skill_spec(names),
            self._tool_activate_skill,
            category="skills",
            keywords=list(ACTIVATE_SKILL_TOOL_KEYWORDS),
            always_loaded=True,
        )
        self.tool_registry.register(
            READ_SKILL_RESOURCE_SPEC,
            self._tool_read_skill_resource,
            category="skills",
            keywords=list(READ_SKILL_RESOURCE_TOOL_KEYWORDS),
        )
        self.tool_registry.register(
            SEARCH_SKILL_RESOURCES_SPEC,
            self._tool_search_skill_resources,
            category="skills",
            keywords=list(SEARCH_SKILL_RESOURCES_TOOL_KEYWORDS),
        )
        self.tool_registry.register(
            RUN_SKILL_SCRIPT_SPEC,
            self._tool_run_skill_script,
            category="skills",
            keywords=list(RUN_SKILL_SCRIPT_TOOL_KEYWORDS),
        )
        self._skill_tools_registered = True
        self._skill_registered_names = list(names)

    # ── catalog 扫描与系统提示块 ────────────────────────────────

    def _scan_skill_catalog(self, *, context_window_tokens: int | None) -> SkillCatalog:
        config = self.config.skills
        skills = scan_skills(resolve_catalog_dir(config.catalog_dir))
        skills = self._drop_blocked_skill_descriptions(skills)
        budget = derive_catalog_budget_bytes(context_window_tokens, config.catalog_max_bytes)
        return build_catalog(skills, budget_bytes=budget)

    @staticmethod
    def _drop_blocked_skill_descriptions(skills: list[LoadedSkill]) -> list[LoadedSkill]:
        """description 进系统提示静态段（全员可见），命中拦截词的 skill 整只剔除。"""
        sensitive = _get_sensitive_filter()
        if not sensitive.is_loaded:
            return skills
        kept = []
        for skill in skills:
            scan = sensitive.scan(skill.metadata.description)
            if scan.blocked:
                logger.warning(
                    "跳过 skill %s [description-blocked]：描述命中拦截词，已从 catalog 剔除",
                    skill.name,
                )
                continue
            kept.append(skill)
        return kept

    def prepare_skill_catalog_for_turn(self, *, provider, model: str) -> str:
        """每轮 tool specs 计算前调用：现扫目录、按需惰性注册、返回渲染块。

        调用方拿返回值直接构建系统提示（同轮不再二次调用
        ``_skills_catalog_block``）：catalog 块与当轮 spec 广告面出自同
        一次扫描，一轮只扫一次目录；新 skill 首次出现的当轮即进入广告面。
        """
        return self._skills_catalog_block(provider=provider, model=model)

    def _skills_catalog_block(self, *, provider, model: str) -> str:
        """每轮构建系统提示时调用：现扫目录、按需惰性注册、渲染静态段末尾块。"""
        if not self.config.skills.enabled:
            return ""
        window = (
            resolve_context_window(provider.model_context_windows, model)
            if provider is not None
            else None
        )
        catalog = self._scan_skill_catalog(context_window_tokens=window)
        self._skills_catalog_by_name = catalog.by_name
        if not catalog.entries:
            return ""
        if not self._skill_tools_registered or self._skill_registered_names != catalog.names:
            self._register_skill_tools(catalog.names)
        return render_catalog_block(catalog)

    def format_skill_list(self, chat_id: int | str, chat_type: str = "group") -> str:
        """``/skill list``：已安装项 + 当前会话已激活项（只读，零历史语义）。"""
        if not self.config.skills.enabled:
            return "Skill 功能当前未启用（config/llm.toml [skills] enabled = false）。"
        skills = scan_skills(resolve_catalog_dir(self.config.skills.catalog_dir))
        scope = self.build_chat_scope_key(chat_id, chat_type)
        return render_skill_list(skills, self._skill_activations.activated_names(scope))

    # ── handlers ────────────────────────────────────────────────

    def _skills_disabled_result(self) -> LLMToolOutput | None:
        if not self.config.skills.enabled:
            return LLMToolOutput(
                content="Skill 功能当前未启用（config/llm.toml [skills] enabled = false）。",
                is_error=True,
            )
        return None

    def _tool_activate_skill(
        self, arguments: dict[str, object], context: ToolExecutionContext
    ) -> str | LLMToolOutput:
        disabled = self._skills_disabled_result()
        if disabled is not None:
            return disabled
        name = str(arguments.get("name", "")).strip()
        scope = self._context_scope_key(context)
        skill = self._skills_catalog_by_name.get(name)
        record = True
        if skill is not None:
            sensitive = _get_sensitive_filter()
            if sensitive.is_loaded:
                # 登记先于结果管道：预扫与管道逐字节同源的注入文本，命中拦截
                # 则本次不登记——正文会被管道整段丢弃，留下登记会让重试只
                # 拿到"已激活"短文本而永远拿不到正文。
                scan = sensitive.scan(
                    format_activation_block(skill, status=ACTIVATION_STATUS_ACTIVATED)
                )
                if scan.blocked:
                    _log_sensitive_hits(f"skill_activation:{name}", scope, scan)
                    record = False
        return activate_skill(
            name=name,
            skills=self._skills_catalog_by_name,
            state=self._skill_activations,
            scope=scope,
            record=record,
        )

    def _tool_read_skill_resource(
        self, arguments: dict[str, object], context: ToolExecutionContext
    ) -> str | LLMToolOutput:
        disabled = self._skills_disabled_result()
        if disabled is not None:
            return disabled
        start_line = arguments.get("start_line")
        end_line = arguments.get("end_line")
        return read_skill_resource(
            skill_name=str(arguments.get("skill", "")).strip(),
            path=str(arguments.get("path", "")).strip(),
            skills=self._skills_catalog_by_name,
            state=self._skill_activations,
            scope=self._context_scope_key(context),
            max_bytes=self.config.skills.resource_max_bytes,
            start_line=start_line if isinstance(start_line, int) else None,
            end_line=end_line if isinstance(end_line, int) else None,
        )

    def _tool_search_skill_resources(
        self, arguments: dict[str, object], context: ToolExecutionContext
    ) -> str | LLMToolOutput:
        disabled = self._skills_disabled_result()
        if disabled is not None:
            return disabled
        return search_skill_resources(
            skill_name=str(arguments.get("skill", "")).strip(),
            query=str(arguments.get("query", "")),
            skills=self._skills_catalog_by_name,
            state=self._skill_activations,
            scope=self._context_scope_key(context),
            is_regex=bool(arguments.get("is_regex", False)),
            case_sensitive=bool(arguments.get("case_sensitive", False)),
            max_results=self.config.skills.search_max_results,
            max_output_bytes=self.config.skills.search_max_output_bytes,
        )

    async def _tool_run_skill_script(
        self, arguments: dict[str, object], context: ToolExecutionContext
    ) -> str | LLMToolOutput:
        disabled = self._skills_disabled_result()
        if disabled is not None:
            return disabled
        raw_args = arguments.get("args", [])
        if not isinstance(raw_args, list) or any(not isinstance(item, str) for item in raw_args):
            return LLMToolOutput(content="args 必须是字符串数组。", is_error=True)
        timeout_ms = arguments.get("timeout_ms")
        return await run_skill_script(
            skill_name=str(arguments.get("skill", "")).strip(),
            path=str(arguments.get("path", "")).strip(),
            script_args=raw_args,
            timeout_ms=timeout_ms if isinstance(timeout_ms, int) else None,
            skills=self._skills_catalog_by_name,
            state=self._skill_activations,
            scope=self._context_scope_key(context),
            default_timeout_ms=self.config.skills.script_timeout_ms,
            max_output_bytes=self.config.skills.script_max_output_bytes,
        )
