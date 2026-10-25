"""
LLM Service — framework-agnostic core.

Moved from ``plugins/llm_runtime.py`` so that the business logic lives
inside ``quickquip/`` with no NoneBot2 dependency.  The NoneBot2 plugin
layer now re-exports from here via ``plugins/llm_runtime.py``.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import asdict, replace
from copy import deepcopy
import json
from datetime import datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.common.sensitive_filter import (
    DEFAULT_BLOCK_REPLY,
    SCRUB_PLACEHOLDER,
    SensitiveFilter,
    get_filter as _get_sensitive_filter,
    log_hits as _log_sensitive_hits,
    reload_filter as _reload_sensitive_filter,
)
from quickquip.llm.config import (
    DISABLED_PROVIDER_REPLY,
    LLMConfig,
    PersonaConfig,
    ProviderConfig,
    provider_builtin_search_active,
)
from quickquip.llm.history_projection import HistoryProjectionError
from quickquip.llm.epoch_history import select_history
from quickquip.llm.history_safety import prepare_safe_history
from quickquip.llm.request_budget import (
    RequestBudgetExceeded,
    derive_replay_budget,
    enforce_request_budget,
)
from quickquip.llm.agent_records import LoopStatus, TriggerKind
from quickquip.llm.service_parts.agent_runtime import DeliveryAborted, TurnRecorder
from quickquip.llm.service_parts.scope_gate import ScopeGate
from quickquip.llm.store_parts.agent_records import (
    AgentStoreError, LoopNotWritable, ScopeGenerationMismatch,
)
from quickquip.llm.identity import (
    IdentityIndex,
    collect_known_participants,
    collect_mention_profiles,
)
from quickquip.common.identity_sources import IdentityRepository, identities
from quickquip.llm.image_preprocessor import ImageDescription, ImagePreprocessor
from quickquip.llm.image_routing import (
    FORWARD_IMAGE_CONTEXT_PREFIX,
    RECENT_IMAGE_CONTEXT_PREFIX,
)
from quickquip.llm.mcp import MCPClientManager
from quickquip.llm.prompting import (
    build_messages,
    build_system_prompt,
    build_turn_envelope_segments,
    merge_image_urls,
)
from quickquip.llm.token_estimate import estimate_tokens
from quickquip.llm.envelope_cache import EnvelopeBreakdownCache
from quickquip.llm.epoch import (
    EpochKey,
    EpochManager,
    EpochParams,
    estimate_rows_budget,
)
from quickquip.llm.provider import (
    LLMProviderError,
    LLMRequest,
    build_provider_client,
)
from quickquip.llm.provider.owner import build_response_owner, primary_endpoint_url
from quickquip.llm.quick_judge import (
    QuickJudgeResult as QuickJudgeResult,  # noqa: F401 — re-exported for callers/tests
    run_quick_judge,
    run_quick_judge_detailed,
)
from quickquip.llm.reply_chain import (
    BUDGET_EXCEEDED_REPLY,
    LLM_RULE_NAME as LLM_RULE_NAME,  # noqa: F401 — re-exported via plugins/llm_runtime
    MAX_QUOTED_MESSAGE_CHARS as MAX_QUOTED_MESSAGE_CHARS,  # noqa: F401 — re-exported via plugins/llm_runtime
    TurnRequestAssembler,
    build_raw_turn_text,
    finalize_reply_text,
    image_caption_blob,
    normalize_turn_input,
    reply_result,
)
from quickquip.llm.reply_types import ChatTurnRequest, ReplyResult
from quickquip.llm.session import SessionIdentity, SessionInvalidated, SessionStoreError
from quickquip.llm.service_parts.constants import (
    DEFAULT_ENABLED_TOOLS as DEFAULT_ENABLED_TOOLS,  # noqa: F401 — re-exported via plugins/llm_runtime
    MAX_MEMORY_RETRIEVAL_ITEMS,
    MAX_STORED_CONVERSATION_MESSAGES,
    MAX_STORED_MEMORY_ITEMS as MAX_STORED_MEMORY_ITEMS,  # noqa: F401 — re-exported via plugins/llm_runtime
    MAX_TRIGGER_CONTEXT_MESSAGES,
    PASSIVE_TRIGGER_QUEUE_PATIENCE_S,
    PRIVATE_UNAVAILABLE_TOOLS as PRIVATE_UNAVAILABLE_TOOLS,  # noqa: F401 — re-exported via plugins/llm_runtime
    SEARCH_TOOL_FAILSAFE_MAX_CALLS_PER_ROUND,
    SEARCH_TOOL_FAILSAFE_MAX_ROUNDS,
    SEARCH_TOOL_NAME,
    TOOL_LIST_NAME,
    TOOL_SEARCH_NAME,
)
from quickquip.llm.service_parts import (
    AutoMemoryMixin,
    DrawSvgToolMixin,
    HealthMixin,
    ImagesMixin,
    McpLifecycleMixin,
    ScheduleMessagesToolMixin,
    SingleShotEntriesMixin,
    SkillsToolMixin,
    ScopeMixin,
    StateMixin,
    ToolMixin,
)
from quickquip.llm.usage import (
    envelope_meter,
    epoch_meter,
    epoch_rows_meter,
    media_meter,
    patch_meter,
    usage_scope,
)
from quickquip.llm.settings import ResolvedGroupSettings, resolve_group_settings
from quickquip.llm.store import LLMStore
from quickquip.llm.tool_registry import ToolRegistry
from quickquip.llm.runtime_snapshot import RuntimeSnapshotMixin, chat_model_entry, snapshot_entry
from quickquip.llm.tool_loop import run_tool_call_loop
from quickquip.llm.tools import (
    LLMConversationMessage,
    LLMToolSpec,
    ToolExecutionContext,
    outbound_images_payload,
)
from quickquip.llm.vocab import VocabIndex
from quickquip.common.paths import (
    LLM_DB_PATH,
    LLM_IDENTITIES_YAML_PATH,
    LLM_VOCAB_YAML_PATH,
)
from quickquip.search.web_search import SearXNGSearchClient, format_search_response  # noqa: F401

if TYPE_CHECKING:
    from quickquip.chat.message_stats import GroupStatsTracker
    from quickquip.chat.rule_switch import GroupRuleSwitch
    from quickquip.common.recent_message_buffer import RecentMessageBuffer



from quickquip.common.paths import LLM_CONFIG_DB_PATH

CONFIG_PATH = LLM_CONFIG_DB_PATH
DB_PATH = LLM_DB_PATH
VOCAB_PATH = LLM_VOCAB_YAML_PATH
IDENTITY_PATH = LLM_IDENTITIES_YAML_PATH
_GROUP_CACHE_MAX = 512


logger = logging.getLogger(__name__)

# 被动类触发：闸门排队超耐心预算即取消（§5.2）。主动 @/前缀、私聊、
# 定时不在此列——用户要答案或计划任务按点发话，晚到也要发。
_PASSIVE_QUEUE_KINDS = frozenset(
    {TriggerKind.GROUP_PASSIVE, TriggerKind.BOREDOM}
)


class LLMService(
    RuntimeSnapshotMixin,
    ScopeMixin,
    ToolMixin,
    McpLifecycleMixin,
    DrawSvgToolMixin,
    ScheduleMessagesToolMixin,
    SkillsToolMixin,
    SingleShotEntriesMixin,
    ImagesMixin,
    HealthMixin,
    StateMixin,
    AutoMemoryMixin,
):
    def __init__(
        self,
        config_path: str | Path = CONFIG_PATH,
        db_path: str | Path = DB_PATH,
        vocab_path: str | Path = VOCAB_PATH,
        identity_path: str | Path = IDENTITY_PATH,
        image_preprocessor: ImagePreprocessor | None = None,
        config: LLMConfig | None = None,
        config_service=None,
    ):
        self.config_path = Path(config_path)
        self.config_dir = config_service.config_dir if config_service is not None else (
            self.config_path.parent.parent if self.config_path.parent.name == "managed"
            else self.config_path.parent.parent / "config"
        )
        self.vocab_path = Path(vocab_path)
        self.identity_path = Path(identity_path)
        self.tool_registry = ToolRegistry()
        self.mcp_manager = MCPClientManager()
        self.image_preprocessor = image_preprocessor
        self.stats_tracker: "GroupStatsTracker | None" = None
        # 逐 Turn 交付出口（§5.1）：由适配层绑定；enabled 且缺失时属编程错误。
        self._delivery_sink = None
        self.rule_switch: "GroupRuleSwitch | None" = None
        self.recent_message_buffer: "RecentMessageBuffer | None" = None
        self._init_mcp_lifecycle()
        self._session_presets: dict[str, str] = {}
        # 会话纪元锚点表（进程内）：进程重启 = 冷一次缓存，首请求按 CTX 跨度懒初始化
        self._epochs = EpochManager()
        # 最近一封信封的六段分解（进程内旁路，纪元看板实时态数据源）
        self._envelope_cache = EnvelopeBreakdownCache()
        # 同 scope 轮次串行闸门（设计 §5.2）：新输入在 Loop 边界取得执行权
        self._scope_gate = ScopeGate()
        self._init_auto_memory()
        self._init_error: str | None = None

        self._register_builtin_tools()
        self.config_service = config_service
        if config is None:
            if self.config_service is None:
                from quickquip.llm.config_service import ConfigService
                self.config_service = ConfigService(self.config_path)
                from quickquip.common.paths import CONFIG_LLM_TOML
                from quickquip.llm.config_runtime import initialize_for_bot
                initialize_for_bot(
                    self.config_service,
                    CONFIG_LLM_TOML if self.config_path == CONFIG_PATH else None
                )
            from quickquip.llm.config_document import compile_document
            published = self.config_service.read("published")
            config = compile_document(
                published["document"], config_dir=self.config_dir,
                revision=published["revision"],
            )
        if self.config_service is not None:
            self.scope_settings = self.config_service.scope_settings
        else:
            from quickquip.llm.scope_settings import ScopeSettingsRepository
            from quickquip.llm.config_store import ConfigStore
            from quickquip.llm.config_document import empty_document
            scope_path = Path(db_path).with_name("scope_configuration.db")
            if not scope_path.exists():
                ConfigStore(scope_path).create(empty_document())
            self.scope_settings = ScopeSettingsRepository(scope_path)
        self.config = config
        self._init_configuration_leases()
        # skills 需要在 config 就位后做启动注册；空目录时留待每轮构建系统
        # 提示时惰性注册（热部署，无 reload 钩子）。
        self._init_skills()
        self.register_skill_tools()

        self._identity_repository = (
            identities
            if Path(self.identity_path) == identities.path
            else IdentityRepository(self.identity_path)
        )
        try:
            self.store = LLMStore(db_path, identity_repository=self._identity_repository)
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

        self._group_vocabs: OrderedDict[str, VocabIndex] = OrderedDict()

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
        if len(self._group_vocabs) >= _GROUP_CACHE_MAX:
            self._group_vocabs.popitem(last=False)
        self._group_vocabs[cache_key] = merged
        return merged

    @property
    def storage_available(self) -> bool:
        """Conversation storage can serve persistent chat and deployment readiness."""
        return self.store is not None and not self.store._unavailable

    @property
    def identities(self) -> IdentityIndex:
        return self._identity_repository.snapshot("").index

    @identities.setter
    def identities(self, value: IdentityIndex) -> None:
        self._identity_repository.set_base_index(value)

    def _resolve_identities(self, group_id: str) -> IdentityIndex:
        return self._identity_repository.snapshot(group_id).index

    def group_identities(self, group_id: str) -> IdentityIndex:
        """按群返回合并后的身份索引，供装配层等外部调用方使用。"""
        return self._resolve_identities(group_id)

    def reload_config(self) -> LLMConfig:
        if self.config_service is None:
            return self.config
        from quickquip.llm.config_document import compile_document
        published = self.config_service.read("published")
        config = compile_document(
            published["document"], config_dir=self.config_dir,
            revision=published["revision"],
        )
        if config.mcp != self.config.mcp:
            raise RuntimeError("MCP 配置更新须通过配置应用任务执行")
        self.activate_configuration(self.prepare_configuration(config))
        _reload_sensitive_filter()
        self.rebuild_image_preprocessor()
        self.vocab = VocabIndex.from_file(self.vocab_path)
        self._identity_repository.invalidate()
        identities.invalidate()
        self._group_vocabs.clear()
        return self.config

    def reload_personas(self) -> tuple[int, str | None]:
        """Reload independent files from ``config/personas/``.

        Does **not** touch providers / MCP / runtime — those stay as loaded at
        startup, since reloading them requires restarting provider clients and
        reinitialising MCP sessions. Returns ``(count, error_message)``; on
        error or an empty result, the previous ``self.config.personas`` is kept.
        """
        try:
            from quickquip.llm.personas import load_personas
            new_personas = load_personas(self.config_dir / "personas")
        except Exception as exc:
            return 0, str(exc)
        if not new_personas:
            return 0, "配置中没有可用的人格"
        runtime = self.config.runtime
        if runtime.default_persona not in new_personas:
            runtime = replace(runtime, default_persona=next(iter(new_personas)))
        self.config = replace(self.config, personas=new_personas, runtime=runtime)
        return len(new_personas), None

    def get_chat_settings(
        self, chat_id: int | str, chat_type: str = "group"
    ) -> ResolvedGroupSettings:
        scope_key = self.build_chat_scope_key(chat_id, chat_type)
        settings = resolve_group_settings(self.scope_settings, self.config, scope_key)
        if chat_type == "private":
            settings = replace(
                settings,
                enabled=self.store.private_chat_active(str(chat_id)),
                allow_at=False,
            )
        return settings

    def get_group_settings(self, group_id: int | str) -> ResolvedGroupSettings:
        return self.get_chat_settings(group_id, chat_type="group")

    def _update_chat_settings(
        self, chat_id: int | str, chat_type: str = "group", **fields: object
    ) -> None:
        scope_key = self.build_chat_scope_key(chat_id, chat_type)
        if self.config_service is not None:
            self.config_service.update_group_override(scope_key, **fields)
        else:
            self.scope_settings.update_group_settings(scope_key, **fields)

    def _build_system_prompt(
        self,
        persona: PersonaConfig,
        group_id: int | str,
        chat_type: str,
        tool_specs: list[LLMToolSpec],
        provider_style_overrides: str = "",
        session_preset: str = "",
        provider_id: str | None = None,
        builtin_search_active: bool = False,
        skills_catalog_block: str = "",
    ) -> str:
        return build_system_prompt(
            persona=persona,
            group_id=group_id,
            tool_specs=tool_specs,
            search_tool_name=SEARCH_TOOL_NAME,
            search_mode=(
                "builtin"
                if builtin_search_active
                else ("searxng" if self.config.auto_search.enabled else "none")
            ),
            tool_discovery_enabled=self._is_tool_discovery_enabled(
                chat_type, provider_id=provider_id
            ),
            tool_search_name=TOOL_SEARCH_NAME,
            tool_list_name=TOOL_LIST_NAME,
            deferred_tool_categories=self._get_deferred_tool_categories(
                chat_type, provider_id=provider_id
            ),
            chat_type=chat_type,
            provider_style_overrides=provider_style_overrides,
            session_preset=session_preset,
            skills_catalog_block=skills_catalog_block,
        )

    def _build_turn_envelope(
        self,
        group_id: int | str,
        chat_type: str,
        prompt: str,
        memories: list[dict[str, object]],
        participants: list[dict[str, str]] | None = None,
        mention_profiles: list[dict[str, str]] | None = None,
    ) -> dict[str, str]:
        # 时钟唯一注入点：信封以外的 prompt 组装全链路无时钟。返回六段分解，
        # join 由 TurnRequestAssembler 统一执行（字节口径单点）。
        return build_turn_envelope_segments(
            now=datetime.now(ZoneInfo(BEIJING_TIMEZONE)),
            prompt=prompt,
            memories=memories,
            vocab=self._resolve_vocab(str(group_id)),
            chat_type=chat_type,
            participants=participants,
            mention_profiles=mention_profiles,
        )

    def _collect_mention_profiles(
        self,
        *,
        chat_id: int | str,
        mentioned_qq_ids: list[str],
        prompt: str,
        quoted_text: str,
        forward_text: str,
        history: list[dict[str, object]],
        scene_patch: list[dict[str, str]] | None,
        current_user_id: str,
        quoted_user_id: str,
    ) -> list[dict[str, str]]:
        """信封档案编排下沉薄委托：本体在 ``llm/identity.py``。"""
        return collect_mention_profiles(
            self._resolve_identities(str(chat_id)),
            mentioned_qq_ids=mentioned_qq_ids,
            prompt=prompt,
            quoted_text=quoted_text,
            forward_text=forward_text,
            history=history,
            scene_patch=scene_patch,
            current_user_id=current_user_id,
            quoted_user_id=quoted_user_id,
        )

    @snapshot_entry
    async def quick_judge(self, prompt: str, max_tokens: int | None = None) -> str:
        """
        一次性极速判定的纯文本契约（现存调用方：draw_svg 内容裁决）。
        结构化判定（awakening、context_rules、auto_memory）走
        ``quick_judge_detailed``。不走群配置、不注入记忆、不启用工具，
        只发单条 system+user；优先使用 [triggers.quick_judge] 配置的
        provider/model，max_tokens 缺省沿用其 max_tokens。
        """
        # 薄委托：通道本体在 quickquip.llm.quick_judge。显式传本模块级
        # build_provider_client，保持既有 patch 点有效，且不向通道传递 self。
        return await run_quick_judge(
            self.config, prompt, max_tokens, client_builder=build_provider_client
        )

    @snapshot_entry
    async def quick_judge_detailed(
        self, prompt: str, max_tokens: int | None = None
    ) -> QuickJudgeResult:
        """``quick_judge`` 的结构化内部通道：按结果类别返回诊断字段，
        不抛 provider 异常。诊断只含 provider/model/类别/finish reason/
        token/耗时，禁止携带 prompt、模型原始响应、凭据或 endpoint。"""
        return await run_quick_judge_detailed(
            self.config, prompt, max_tokens, client_builder=build_provider_client
        )

    def persona_interest_topics(self, persona_id: str) -> list[str]:
        """persona extras 中 awakening 兴趣话题的窄读取（清洗为非空字符串列表）。

        配置形状知识归 persona 所有者；唤醒域经 ``PersonaTopicsSource``
        结构化接口消费，不直达 ``config.personas`` 内部。
        """
        persona = self.config.personas.get(persona_id)
        if persona is None:
            return []
        topics = persona.extras.get("awakening", {}).get("interest_topics", [])
        if not isinstance(topics, list):
            return []
        return [str(t).strip() for t in topics if str(t).strip()]

    def bind_delivery_sink(self, sink) -> None:
        """绑定逐 Turn 交付出口（adapters 装配时调用）。"""
        self._delivery_sink = sink

    def _build_request_guard(self, provider: ProviderConfig):
        """逐轮预算门禁闭包（§8.3）：超限以 DeliveryAborted 终止 Loop。"""
        from quickquip.llm.service_parts.agent_runtime import DeliveryAborted

        def _guard(request: LLMRequest) -> None:
            try:
                enforce_request_budget(self.config, provider, request)
            except RequestBudgetExceeded as exc:
                logger.warning(
                    "request budget exceeded mid-loop provider=%s model=%s: %s",
                    provider.id, request.model, exc,
                )
                raise DeliveryAborted("request_budget_exceeded") from exc

        return _guard

    def maintain_agent_retention(self, scope_key: str) -> None:
        """D5 保留维护（§8.4）：Loop 关闭后调用，按三上限清理最旧完整 Loop。

        数量或字节硬上限要求删除活动记录时，先推进受影响纪元再清理。
        """
        from quickquip.llm.store_parts.agent_records import RetentionPolicy

        policy = RetentionPolicy(
            retention_days=self.config.runtime.agent_record_retention_days,
            max_loops=self.config.runtime.agent_record_max_loops_per_scope,
            max_bytes=self.config.runtime.agent_record_max_bytes_per_scope,
        )
        active_anchors = [
            anchor
            for anchor in [self._epochs.oldest_anchor(scope_key)]
            if anchor is not None
        ]
        report = self.store.prune_closed_loops(scope_key, active_anchors, policy)
        if report.required_anchor_id is not None:
            self._epochs.advance_scope(
                scope_key, report.required_anchor_id, store=self.store, reason="retention",
            )
            self._skill_activations.clear_scope(scope_key)
            remaining = self._epochs.oldest_anchor(scope_key)
            report = self.store.prune_closed_loops(
                scope_key, [remaining] if remaining is not None else [], policy,
            )
        if report.deleted_loop_ids:
            logger.info(
                "agent record pruned scope=%s loops=%d",
                scope_key, len(report.deleted_loop_ids),
            )
        if report.blocked_active_anchors:
            logger.info(
                "agent record hard cap blocked by active epoch scope=%s anchors=%s",
                scope_key, list(report.blocked_active_anchors),
            )

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
        include_recent_images: bool = False,
        recent_images_messages: list[dict[str, str]] | None = None,
        turn_envelope: str = "",
        projected_history_segments: dict[str, list[LLMConversationMessage]] | None = None,
    ) -> list[LLMConversationMessage]:
        return build_messages(
            prompt=prompt,
            image_urls=image_urls,
            history=history,
            recent_messages=recent_messages,
            max_trigger_context_messages=MAX_TRIGGER_CONTEXT_MESSAGES,
            recent_images_messages=recent_images_messages,
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
            include_recent_images=include_recent_images,
            turn_envelope=turn_envelope,
            projected_history_segments=projected_history_segments,
        )

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
        """信封参与者编排下沉薄委托：本体在 ``llm/identity.py``。"""
        return collect_known_participants(
            self._resolve_identities(group_id),
            user_id=user_id,
            sender_name=sender_name,
            history=history,
            recent_messages=recent_messages,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
        )

    def _begin_agent_recorder(
        self,
        *,
        scope_key: str,
        chat_type: str,
        user_id: int | str,
        sender_name: str,
        stored_prompt: str,
        message_id: str | None,
        store_user_message: bool,
        normalized_quoted_text: str,
        normalized_quoted_image_urls: list[str],
        normalized_forward_text: str,
        normalized_forward_image_urls: list[str],
        image_descriptions: list[ImageDescription] | None,
        delivery_sink=None,
        trigger_kind: TriggerKind | None = None,
        agent_delivery_intermediate_enabled: bool,
        agent_delivery_final_enabled: bool,
        expected_generation: int | None = None,
    ):
        """创建 Loop 与 user 触发行（§5.3.1），返回 TurnRecorder。

        合成触发（``store_user_message=False``）与 store 不可用时本期保持
        旧路径（无 Loop 记录），属已记录的渐进边界。
        """
        from quickquip.llm.service_parts.agent_runtime import RecorderConfig, TurnRecorder
        from quickquip.llm.store_parts.agent_records import UserTriggerPayload

        if not store_user_message or self.store is None:
            return None
        current_identity = self._resolve_identities(
            scope_key.removeprefix("private:")
        ).resolve_user(user_id, sender_name)
        raw_turn = build_raw_turn_text(
            stored_prompt,
            quoted_text=normalized_quoted_text,
            quoted_image_urls=normalized_quoted_image_urls,
            forward_text=normalized_forward_text,
            forward_image_urls=normalized_forward_image_urls,
            image_descriptions=image_descriptions,
        )
        generation = expected_generation
        if generation is None:
            generation, _ = self.store.agent_scope_state(scope_key)
        if trigger_kind is not None:
            trigger = trigger_kind
        else:
            trigger = (
                TriggerKind.PRIVATE_DIRECT if chat_type == "private" else TriggerKind.GROUP_DIRECT
            )
        try:
            handle = self.store.begin_loop(
                scope_key,
                generation,
                trigger,
                UserTriggerPayload(
                    user_id=str(user_id),
                    sender_name=sender_name,
                    canonical_name=current_identity.canonical_name,
                    content=stored_prompt,
                    raw_content=raw_turn,
                    message_id=str(message_id) if message_id else None,
                ),
            )
        except ScopeGenerationMismatch as exc:
            raise SessionInvalidated("会话在开始执行前已失效") from exc
        except LoopNotWritable as exc:
            # 闸门应已串行化同 scope 轮次：仍撞单飞约束即闸门旁路（编程
            # 错误），告警计数后走既有无记录路径兜底。
            self._scope_gate.record_bypass(scope_key, str(exc))
            return None
        except AgentStoreError:
            logger.exception("begin_loop 失败 scope=%s，本轮退回无记录路径", scope_key)
            return None
        runtime = self.config.runtime
        return TurnRecorder(
            store=self.store,
            handle=handle,
            config=RecorderConfig(
                agent_delivery_intermediate_enabled=agent_delivery_intermediate_enabled,
                agent_delivery_final_enabled=agent_delivery_final_enabled,
                reply_split_threshold_chars=runtime.reply_split_threshold_chars,
                reply_chunk_max_chars=runtime.reply_chunk_max_chars,
                reply_max_chunks_per_loop=runtime.reply_max_chunks_per_loop,
            ),
            sink=delivery_sink or self._delivery_sink,
            sensitive_scan=(
                _get_sensitive_filter().scan
                if _get_sensitive_filter().is_loaded
                else None
            ),
        )

    async def _run_tool_call_loop(
        self,
        *,
        provider: ProviderConfig,
        request: LLMRequest,
        context: ToolExecutionContext,
        turn_recorder: TurnRecorder | None = None,
        request_guard=None,
    ):
        epoch_key = EpochKey(context.chat_scope, provider.id, request.model)
        return await run_tool_call_loop(
            provider=provider,
            request=request,
            context=context,
            turn_recorder=turn_recorder,
            request_guard=request_guard,
            on_provider_activity=lambda: self._epochs.note_activity(
                epoch_key, epoch_id=request.epoch_id,
            ),
            build_provider_client=build_provider_client,
            tool_registry=self.tool_registry,
            runtime_config=self.config.runtime,
            logger=logger,
            search_tool_name=SEARCH_TOOL_NAME,
            search_failsafe_max_rounds=SEARCH_TOOL_FAILSAFE_MAX_ROUNDS,
            search_failsafe_max_calls_per_round=SEARCH_TOOL_FAILSAFE_MAX_CALLS_PER_ROUND,
            search_max_calls_per_round=self.config.auto_search.search_max_calls_per_round,
            tool_discovery_enabled=self._is_tool_discovery_enabled(
                context.chat_type, provider_id=provider.id
            ),
            tool_search_name=TOOL_SEARCH_NAME,
            tool_list_name=TOOL_LIST_NAME,
            enabled_tool_names=self._get_enabled_tool_names(
                chat_type=context.chat_type, provider_id=provider.id
            ),
            initial_tool_names=[spec.name for spec in request.tools],
            tool_discovery_search_limit=self.config.tools.discovery_search_limit,
            tool_discovery_max_loaded_tools=self.config.tools.discovery_max_loaded_tools,
            image_preprocessor=self.image_preprocessor,
        )

    def _load_scrubbed_history_and_participants(
        self,
        *,
        chat_id: int | str,
        chat_type: str,
        scope_key: str,
        settings: ResolvedGroupSettings,
        sensitive: SensitiveFilter,
        user_id: int | str,
        sender_name: str,
        recent_messages: list[dict[str, str]] | None,
        message_id: str | None,
        quoted_sender_name: str,
        quoted_user_id: str,
        epoch_key: EpochKey,
        epoch_params: EpochParams,
        provider: ProviderConfig | None = None,
        replay_budget: int | None = None,
    ) -> tuple[
        list[dict[str, object]],
        list[dict[str, str]],
        list[dict[str, str]] | None,
        dict[str, list[LLMConversationMessage]],
    ]:
        # 会话纪元读取：只追加锚点窗口（懒初始化/冷场/触顶/行数兜底的推进判定
        # 全部在 EpochManager 内），纪元内前缀逐字节稳定。auto_memory 仍走
        # list_recent_conversation_messages 的 DESC LIMIT 尾读——两个消费者
        # 两种读模式，勿在此"统一"。
        epoch_event = self._epochs.maybe_advance(epoch_key, store=self.store, params=epoch_params)
        if epoch_event is not None:
            # 锚点推进 = 窗口内历史被丢弃：激活注入的正文可能随之出窗，
            # 清掉登记让模型需要时重新激活（重新注入正文）。
            self._skill_activations.clear_scope(scope_key)
        self._epochs.activate(epoch_key, store=self.store)
        anchor = self._epochs.current_anchor(epoch_key) or 0
        if settings.history_limit is not None:
            # 显式 /llm context_limit 覆盖：尊重"更小窗口"意图，退化为该会话的
            # 行数兜底滚动窗（每轮按行数重新锚定）。
            backstop = self.store.find_anchor_row_id_by_rows(scope_key, settings.history_limit)
            if backstop is not None:
                backstop = self.store.align_history_anchor(scope_key, backstop)
                if backstop > anchor:
                    self._epochs.rebuild(
                        epoch_key, store=self.store, reason="context_limit", anchor=backstop,
                    )
                    anchor = self._epochs.current_anchor(epoch_key) or 0
        # 窗口守卫（Deep-CR L1-3/L3-1）：生效锚点越过登记的激活尾部即激活轮
        # 出窗，清掉登记让重新激活走完整注入——否则去重短路会向模型声称
        # "正文不再重复注入"而正文已不可见。覆盖锚点推进类收缩（行数兜底；
        # 纪元推进另有整体清除）；词表归档与投影降级类（行不动、可见面变）
        # 不在本守卫内，残留登记的自救是模型自行 read_skill_resource。
        self._skill_activations.drop_outdated(scope_key, anchor)
        history = self.store.list_conversation_messages_since(
            scope_key, anchor, limit=None,
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
        projected_segments: dict[str, list[LLMConversationMessage]] = {}
        if provider is not None:
            projected_segments = self._projected_history_segments(
                scope_key=scope_key,
                history=history,
                provider=provider,
                model=epoch_key.model,
                sensitive=sensitive,
                effort=settings.reasoning_effort,
                replay_budget=replay_budget,
            )

        # 【现场】补丁自取：仅群聊、调用方未显式注入（None=自取，[]=显式空，
        # 后者是测试注入口）、buffer 已绑定。去重 = history 已覆盖的
        # message_id ∪ 当前触发消息（_remember_recent_message 先于本调用，
        # 触发消息已在 buffer）。读即服役：取出后立即推进游标。
        exclude_ids = {
            str(item["message_id"]) for item in history if item.get("message_id")
        }
        if message_id:
            exclude_ids.add(str(message_id))
        if (
            recent_messages is None
            and chat_type == "group"
            and self.recent_message_buffer is not None
        ):
            recent_messages = self.recent_message_buffer.list_patch(
                scope_key,
                exclude_message_ids=exclude_ids,
                budget_tokens=self.config.runtime.recent_context_token_budget,
                floor_seconds=self.config.runtime.recent_context_floor_seconds,
                token_estimator=estimate_tokens,
            )
            self.recent_message_buffer.note_patch_served(scope_key)
        if recent_messages is not None:
            recent_messages = [
                item for item in recent_messages
                if not item.get("message_id") or str(item["message_id"]) not in exclude_ids
            ]
        participants = self._collect_known_participants(
            user_id=user_id,
            sender_name=sender_name,
            history=history,
            recent_messages=recent_messages,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
            group_id=str(chat_id),
        )
        return history, participants, recent_messages, projected_segments

    def _projected_history_segments(
        self, *, scope_key: str, history: list[dict[str, object]],
        provider: ProviderConfig, model: str, sensitive: SensitiveFilter,
        effort: str = "", replay_budget: int | None = None,
    ) -> dict[str, list[LLMConversationMessage]]:
        """Freeze allowed historical expressions, rebuilding the epoch on changes."""
        key = EpochKey(scope_key, provider.id, model)
        params = self.config.resolve_epoch_params(provider)
        if self._epochs.current_id(key) is None:
            self._epochs.maybe_advance(key, store=self.store, params=params)
        loop_ids = {str(row["agent_loop_id"]) for row in history if row.get("agent_loop_id")}
        loaded = self.store.load_closed_loops_by_ids(scope_key, loop_ids) if loop_ids else []
        closed_ids = {loop.loop_id for loop in loaded}
        # An active Loop is never installed as historical input.
        history[:] = [row for row in history if not row.get("agent_loop_id")
                      or row["agent_loop_id"] in closed_ids]
        loaded, archive_loop_ids = prepare_safe_history(loaded, sensitive)
        target = None if provider.fallback_urls else build_response_owner(
            provider, primary_endpoint_url(provider, model), model,
        )
        budget = derive_replay_budget(self.config, provider, model)
        profile = json.dumps((asdict(target) if target else None, provider.protocol,
                              budget, effort or provider.reasoning_effort), sort_keys=True)
        previous = self._epochs.frozen_history(key)
        try:
            selection = select_history(
                history, loaded, previous=previous, target=target,
                protocol=provider.protocol, profile=profile, budget=budget,
                target_ratio=params.hot_target_tokens / params.cap_tokens,
                archive_loop_ids=archive_loop_ids, effort=effort or provider.reasoning_effort,
                rebuild_budget=replay_budget,
            )
        except HistoryProjectionError:
            logger.exception("history projection failed scope=%s; using stored text", scope_key)
            self._epochs.rebuild(key, store=self.store, reason="history")
            return {}
        if selection.reason:
            self._epochs.rebuild(
                key, store=self.store, reason=selection.reason, anchor=selection.anchor,
            )
            self._skill_activations.clear_scope(scope_key)
            logger.info(
                "epoch history rebuilt scope=%s epoch=%s reason=%s replay_tokens=%d",
                scope_key, self._epochs.current_id(key), selection.reason,
                selection.frozen.replay_tokens,
            )
        history[:] = selection.frozen.rows
        self._epochs.install_history(key, selection.frozen)
        return deepcopy(selection.frozen.segments)

    def _persist_turn_and_build_reply(
        self,
        *,
        chat_id: int | str,
        session: SessionIdentity,
        session_generation: int,
        user_id: int | str,
        sender_name: str,
        scope_key: str,
        settings: ResolvedGroupSettings,
        provider: ProviderConfig,
        model: str,
        text: str,
        stored_prompt: str,
        store_user_message: bool,
        trigger_auto_memory: bool,
        message_id: str | None,
        normalized_quoted_text: str,
        normalized_quoted_image_urls: list[str],
        normalized_forward_text: str,
        normalized_forward_image_urls: list[str],
        image_descriptions: list[ImageDescription] | None = None,
        tool_context: ToolExecutionContext,
        recorder_rows_written: bool = False,
    ) -> dict[str, object]:
        current_identity = self._resolve_identities(str(chat_id)).resolve_user(user_id, sender_name)
        user_message = None
        if store_user_message and not recorder_rows_written:
            raw_turn = build_raw_turn_text(
                stored_prompt,
                quoted_text=normalized_quoted_text,
                quoted_image_urls=normalized_quoted_image_urls,
                forward_text=normalized_forward_text,
                forward_image_urls=normalized_forward_image_urls,
                image_descriptions=image_descriptions,
            )
            user_message = {
                "user_id": user_id, "sender_name": sender_name,
                "canonical_name": current_identity.canonical_name,
                "content": stored_prompt, "message_id": str(message_id) if message_id else None,
                "raw_content": raw_turn,
            }
        self.store.append_session_reply(
            scope_key, session, session_generation, user_message=user_message,
            assistant_text=None if recorder_rows_written else text,
            floor_id=self._epochs.oldest_anchor(scope_key),
            keep_last=MAX_STORED_CONVERSATION_MESSAGES,
        )

        if trigger_auto_memory and settings.auto_memory_enabled and settings.memory_enabled:
            generation_at_schedule = session_generation
            self.create_configuration_task(
                self._extract_auto_memory(
                    scope_key=scope_key,
                    user_id=user_id,
                    sender_name=sender_name,
                    canonical_name=current_identity.canonical_name,
                    user_text=stored_prompt,
                    assistant_text=text,
                    persona_id=settings.persona_id,
                    expected_generation=generation_at_schedule,
                )
            )

        # 发送回执按群回填无记录路径的 assistant 行（无 agent_turn_row_id 时
        # record_final_receipt 依赖此键定位）；工具外发图片（base64 PNG）由
        # 适配层拼在文本后发送（上限见 MAX_OUTBOUND_TOOL_IMAGES）
        return reply_result(
            text,
            llm_used=True,
            provider_id=provider.id,
            model=model,
            scope_key=scope_key,
            images=outbound_images_payload(tool_context),
        )

    async def _generate_reply_for_scope(self, request: ChatTurnRequest) -> ReplyResult:
        """同 scope 串行闸门（设计 §5.2）：新输入在 Loop 边界取得执行权。

        取得执行权后再做配置解析与上下文装配，满足「取得执行权时再次
        检查」的时序；长轮次（原生生图）期间同 scope 后续轮次在此排队。
        被动类触发（群被动唤醒/无聊唤醒）排队超过耐心预算即取消本轮：
        排到长生成之后的插话已是过期噪音，空回复出口由适配层既有守卫
        静默吞掉；主动/私聊/定时触发不限时——晚到也要发。

        资格复查的有意取舍（§5.2 残余项）：rule_switch 开关、回复掷骰与
        入口限流在适配层排队前消费，锁后不重掷——影响有界（每在途轮至
        多补发一条主动触发），被动类已被耐心预算兜住。
        """
        scope_key = self.build_chat_scope_key(request.chat_id, request.chat_type)
        async with self._scope_gate.guarded(scope_key) as hold:
            if (
                request.trigger_kind in _PASSIVE_QUEUE_KINDS
                and hold.waited_s > PASSIVE_TRIGGER_QUEUE_PATIENCE_S
            ):
                logger.info(
                    "被动触发排队过期取消 scope=%s kind=%s wait_s=%.1f",
                    scope_key, request.trigger_kind, hold.waited_s,
                )
                return reply_result(
                    "", llm_used=False, cancelled_reason="queue_patience_exceeded"
                )
            try:
                if not self.config.load_error and not self.storage_available:
                    raise SessionStoreError("LLM 会话存储不可用")
                return await self._generate_reply_for_scope_locked(request)
            except SessionInvalidated:
                return reply_result("", llm_used=False, cancelled_reason="session_invalidated")
            except SessionStoreError:
                logger.exception("chat session storage failed scope=%s", scope_key)
                return reply_result("会话存储不可用，请稍后重试。", llm_used=False)

    @chat_model_entry
    async def _generate_reply_for_scope_locked(
        self, request: ChatTurnRequest
    ) -> ReplyResult:
        turn = normalize_turn_input(
            request, max_prompt_chars=self.config.runtime.max_prompt_chars
        )
        if not turn.has_content:
            return reply_result(self.config.triggers.empty_prompt_reply, llm_used=False)

        scope_key = self.build_chat_scope_key(request.chat_id, request.chat_type)
        sensitive = _get_sensitive_filter()
        if sensitive.is_loaded:
            input_blob = "\n".join(
                part for part in (
                    turn.prompt,
                    turn.quoted_text,
                    turn.forward_text,
                ) if part
            )
            input_scan = sensitive.scan(input_blob)
            if input_scan.hits:
                _log_sensitive_hits("input", scope_key, input_scan)
            if input_scan.blocked:
                return reply_result(DEFAULT_BLOCK_REPLY, llm_used=False)

        if self.config.load_error:
            return reply_result(f"LLM 配置不可用：{self.config.load_error}", llm_used=False)

        if not self.storage_available:
            raise SessionStoreError("LLM 会话存储不可用")
        settings = self.get_chat_settings(request.chat_id, chat_type=request.chat_type)
        if not settings.enabled:
            return reply_result(
                f"{self._scope_subject(request.chat_type)} LLM 已关闭。", llm_used=False
            )

        provider = self.config.providers.get(settings.provider_id)
        if provider is None:
            return reply_result(f"当前 provider 不存在：{settings.provider_id}", llm_used=False)
        if not provider.enabled:
            return reply_result(
                DISABLED_PROVIDER_REPLY.format(provider_id=settings.provider_id), llm_used=False
            )

        from quickquip.llm.config_document import resolve_model_provider
        try:
            provider = resolve_model_provider(
                self.config, provider.id, settings.model or provider.default_model
            )
        except ValueError:
            return reply_result("当前模型不可用。", llm_used=False)

        persona = self.config.personas.get(settings.persona_id)
        if persona is None:
            return reply_result(f"当前 persona 不存在：{settings.persona_id}", llm_used=False)

        session, session_generation = self.store.get_or_create_chat_session(scope_key)

        def check_session() -> None:
            self.store.assert_chat_session(scope_key, session, session_generation)

        # ── history load + sensitive scrub + 【现场】补丁自取 + participants ──
        # 先于图片预处理：补丁去重要用 history 的 message_id，而预处理的
        # 近期图候选与 participants 都消费补丁。注意 epoch 锚点推进因此早于
        # 预处理早退路径（图片拦截/下载失败），锚点轻幅漂移属可接受边界。
        epoch_key = EpochKey(
            scope_key=scope_key,
            provider_id=provider.id,
            model=settings.model or provider.default_model,
        )
        epoch_params = self.config.resolve_epoch_params(provider)
        (
            history,
            participants,
            scene_patch,
            projected_segments,
        ) = self._load_scrubbed_history_and_participants(
            chat_id=request.chat_id,
            chat_type=request.chat_type,
            scope_key=scope_key,
            settings=settings,
            sensitive=sensitive,
            user_id=request.user_id,
            sender_name=request.sender_name,
            recent_messages=request.recent_messages,
            message_id=request.message_id,
            quoted_sender_name=request.quoted_sender_name,
            quoted_user_id=request.quoted_user_id,
            epoch_key=epoch_key,
            epoch_params=epoch_params,
            provider=provider,
        )

        # ── image preprocessing & non-VLM stripping ──────────────────
        scene_patch_snapshot = list(scene_patch) if scene_patch is not None else None
        # 被动唤醒「看见近期图」是全量快照语义（TTL 窗，list_recent），不随【现场】
        # 补丁的增量游标收窄——无聊唤醒恰在冷场（补丁最空）时触发，增量图源会让
        # 该特性静默失效。文本上下文仍走增量补丁（scene_patch）；显式注入
        # recent_messages（测试注入口）时注入列表即图源，不被 buffer 覆盖。
        if (
            request.include_recent_images
            and request.recent_messages is None
            and request.chat_type == "group"
            and self.recent_message_buffer is not None
        ):
            recent_images_source: list[dict[str, str]] | None = (
                self.recent_message_buffer.list_recent(scope_key)
            )
        else:
            recent_images_source = scene_patch
        image_outcome = await self._preprocess_images_for_model(
            chat_id=request.chat_id,
            scope_key=scope_key,
            provider=provider,
            settings=settings,
            request_image_urls=list(turn.image_urls),
            request_quoted_image_urls=list(turn.quoted_image_urls),
            request_forward_image_urls=list(turn.forward_image_urls),
            normalized_image_urls=turn.image_urls,
            normalized_quoted_image_urls=turn.quoted_image_urls,
            normalized_forward_image_urls=turn.forward_image_urls,
            recent_messages=recent_images_source,
            include_recent_images=request.include_recent_images,
            sensitive=sensitive,
            session=session,
            epoch_id=self._epochs.current_id(epoch_key),
        )
        check_session()
        if isinstance(image_outcome, dict):
            return image_outcome
        effective_image_urls = image_outcome.effective_image_urls
        request_quoted_image_urls = image_outcome.request_quoted_image_urls
        request_forward_image_urls = image_outcome.request_forward_image_urls
        image_descriptions = image_outcome.image_descriptions
        is_non_vision = image_outcome.is_non_vision
        # ── end image preprocessing ─────────────────────────────────
        # 转发图注并入 forward_text：当轮渲染（_build_messages）与落库
        # （_persist_turn_and_build_reply）共用同一变量，两条路径字节一致；
        # 并入后从 image_descriptions 摘除，避免视觉转述行与落库 caption 双重出现
        forward_text = turn.forward_text
        forward_descs = [
            d for d in image_descriptions
            if d.context_label.startswith(FORWARD_IMAGE_CONTEXT_PREFIX)
        ]
        if forward_descs:
            forward_caption_count, forward_caption_blob = image_caption_blob(forward_descs)
            if forward_caption_count:
                forward_text = "\n".join(
                    part
                    for part in (
                        forward_text,
                        f"[转发图片 {forward_caption_count} 张：{forward_caption_blob}]",
                    )
                    if part
                )
                image_descriptions = [
                    d for d in image_descriptions
                    if not d.context_label.startswith(FORWARD_IMAGE_CONTEXT_PREFIX)
                ]
        if self.config.mcp.enabled:
            await self.ensure_mcp_ready()
        memories: list[dict[str, object]] = []
        if settings.memory_enabled:
            memories = self.store.search_memories(
                scope_key,
                user_id=request.user_id,
                query=turn.analysis_prompt or turn.trimmed_prompt,
                limit=min(self.config.runtime.memory_limit, MAX_MEMORY_RETRIEVAL_ITEMS),
            )

        # skills 现扫 + 惰性注册先于 tool specs 计算：新 skill 首次出现的
        # 当轮即进入 spec 广告面；catalog 块与 specs 出自同一次扫描
        # （一轮只扫一次目录）。
        skills_catalog_block = self.prepare_skill_catalog_for_turn(
            provider=provider, model=settings.model
        )
        builtin_search_active = provider_builtin_search_active(provider)
        tool_specs = (
            self._get_enabled_tool_specs(chat_type=request.chat_type, provider_id=provider.id)
            if self.config.runtime.tool_calling_enabled
            else []
        )
        session_preset = (
            self.get_session_preset(scope_key) if request.chat_type == "private" else ""
        )
        system_prompt = self._build_system_prompt(
            persona,
            request.chat_id,
            request.chat_type,
            tool_specs,
            provider_style_overrides=provider.style_overrides,
            session_preset=session_preset,
            provider_id=provider.id,
            builtin_search_active=builtin_search_active,
            skills_catalog_block=skills_catalog_block,
        )
        # 装配对象持有当轮上下文；账本 meter 消费 assemble() 后的最终值。
        assembler = TurnRequestAssembler(
            load_history=self._load_scrubbed_history_and_participants,
            collect_mention_profiles=self._collect_mention_profiles,
            build_turn_envelope=self._build_turn_envelope,
            build_messages=self._build_messages,
            chat_id=request.chat_id,
            chat_type=request.chat_type,
            scope_key=scope_key,
            session=session,
            get_epoch_id=lambda: self._epochs.current_id(epoch_key),
            settings=settings,
            sensitive=sensitive,
            user_id=request.user_id,
            sender_name=request.sender_name,
            message_id=request.message_id,
            quoted_sender_name=request.quoted_sender_name,
            quoted_user_id=request.quoted_user_id,
            epoch_key=epoch_key,
            epoch_params=epoch_params,
            provider=provider,
            scene_patch_snapshot=scene_patch_snapshot,
            mentioned_qq_ids=request.mentioned_qq_ids,
            analysis_prompt=turn.analysis_prompt,
            trimmed_prompt=turn.trimmed_prompt,
            quoted_prompt=turn.quoted_prompt,
            memories=memories,
            effective_image_urls=effective_image_urls,
            recent_images_source=recent_images_source,
            request_quoted_image_urls=request_quoted_image_urls,
            request_forward_image_urls=request_forward_image_urls,
            quoted_is_bot_self=request.quoted_is_bot_self,
            forward_text=forward_text,
            image_descriptions=image_descriptions,
            include_recent_images=request.include_recent_images,
            is_non_vision=is_non_vision,
            tool_specs=tool_specs,
            builtin_search_active=builtin_search_active,
            system_prompt=system_prompt,
        )

        # §8.3 先降级再拒绝：超限时锚点强制缩到热水位（付费 miss 一次），
        # 复用首轮补丁重建请求重试一次；仍超限才终止本轮。
        llm_request = assembler.assemble()
        budget_retry_used = False
        while True:
            try:
                enforce_request_budget(self.config, provider, llm_request)
                break
            except RequestBudgetExceeded as exc:
                logger.warning(
                    "request budget exceeded scope=%s provider=%s model=%s: %s",
                    scope_key, provider.id, llm_request.model, exc,
                )
                if budget_retry_used:
                    return reply_result(
                        BUDGET_EXCEEDED_REPLY,
                        llm_used=False,
                        provider_id=provider.id,
                        model=llm_request.model,
                    )
                degraded = self._epochs.force_advance_to_hot(
                    epoch_key, store=self.store, params=epoch_params
                )
                if degraded is None:
                    frozen = self._epochs.frozen_history(epoch_key)
                    if frozen and frozen.replay_tokens:
                        assembler.replay_budget = max(1, frozen.replay_tokens // 2)
                    elif len(assembler.history) > 4:
                        candidate = int(assembler.history[len(assembler.history) // 2]["id"])
                        aligned = self.store.align_history_anchor(scope_key, candidate)
                        if aligned > (self._epochs.current_anchor(epoch_key) or 0):
                            degraded = self._epochs.rebuild(
                                epoch_key, store=self.store, reason="budget", anchor=aligned,
                            )
                    if degraded is None and assembler.replay_budget is None:
                        return reply_result(
                            BUDGET_EXCEEDED_REPLY, llm_used=False,
                            provider_id=provider.id, model=llm_request.model,
                        )
                self._skill_activations.clear_scope(scope_key)
                budget_retry_used = True
                logger.info("epoch budget rebuild scope=%s", scope_key)
                llm_request = assembler.assemble()
        check_session()
        budget_guard = self._build_request_guard(provider)

        def request_guard(current_request: LLMRequest) -> None:
            check_session()
            budget_guard(current_request)

        tool_context = ToolExecutionContext(
            group_id=request.chat_id,
            user_id=request.user_id,
            sender_name=request.sender_name,
            provider_id=provider.id,
            model=llm_request.model,
            chat_scope=scope_key,
            chat_type=request.chat_type,
        )

        recorder: TurnRecorder | None = None

        def check_error_session() -> None:
            try:
                check_session()
            except (SessionInvalidated, SessionStoreError):
                if recorder is not None:
                    recorder.close(LoopStatus.INTERRUPTED, "session_invalidated")
                raise

        try:
            # 拿到群级 persona 后把聊天主链路升级为带人格归因的 scope；
            # scope 生命周期与 provider 调用同处一个函数，退出即复位。
            # group_id 用 scope_key（群聊 = str(chat_id)，私聊 = private:{id}），
            # 与 auto_memory 等派生调用的归因口径一致。
            recorder = self._begin_agent_recorder(
                scope_key=scope_key,
                chat_type=request.chat_type,
                user_id=request.user_id,
                sender_name=request.sender_name,
                stored_prompt=turn.stored_prompt,
                message_id=request.message_id,
                store_user_message=request.store_user_message,
                normalized_quoted_text=turn.quoted_text,
                normalized_quoted_image_urls=turn.quoted_image_urls,
                normalized_forward_text=forward_text,
                normalized_forward_image_urls=turn.forward_image_urls,
                # 同 _persist_turn_and_build_reply 的落库口径：他人近期图注不落触发者名下。
                image_descriptions=[
                    d for d in image_descriptions
                    if not d.context_label.startswith(RECENT_IMAGE_CONTEXT_PREFIX)
                ] or None,
                delivery_sink=request.delivery_sink,
                trigger_kind=request.trigger_kind,
                agent_delivery_intermediate_enabled=settings.agent_delivery_intermediate_enabled,
                agent_delivery_final_enabled=settings.agent_delivery_final_enabled,
                expected_generation=session_generation,
            )
            # 信封构成缓存：装配最终态已知（预算降级重建后的 assembler），
            # 记最近一次六段分解供纪元看板实时态导出。
            self._envelope_cache.record(epoch_key, assembler.envelope_parts)
            with (
                usage_scope("chat", group_id=scope_key, persona_id=settings.persona_id or None),
                envelope_meter(estimate_tokens(assembler.turn_envelope)),
                epoch_meter(estimate_rows_budget(assembler.history)),
                # 保留条数锯齿的计量源：窗口行数与 token 同口径同生命周期
                epoch_rows_meter(len(assembler.history)),
                # 媒体账本：当轮实际随请求附带的图片数（只有末条 user 消息携带
                # image_urls；非 VLM 剥离后恒 0，0 也是有效信号）
                media_meter(len(assembler.messages[-1].image_urls)),
                # 补丁账本：【现场】块 token 估算，与预算同单位（AVG=预算利用率）。
                # 三态：None=未自取（私聊/buffer 未绑定）；0=自取但补丁为空（有效
                # 信号，与 media 的 0 同理）；正值=自取有货。空补丁轮计入 coverage
                # 分子，否则 patch_coverage 测的是「非空补丁轮占比」而非自取覆盖率
                patch_meter(
                    sum(
                        estimate_tokens(str(item.get("text", "")))
                        for item in assembler.scene_patch
                    )
                    if assembler.scene_patch is not None
                    else None
                ),
            ):
                response = await self._run_tool_call_loop(
                    provider=provider,
                    request=llm_request,
                    context=tool_context,
                    turn_recorder=recorder,
                    request_guard=request_guard,
                )
        except (SessionInvalidated, SessionStoreError):
            if recorder is not None:
                recorder.close(LoopStatus.INTERRUPTED, "session_invalidated")
            raise
        except asyncio.CancelledError:
            if recorder is not None:
                recorder.close(LoopStatus.INTERRUPTED, "request_cancelled")
            raise
        except DeliveryAborted as exc:
            check_error_session()
            if recorder is not None:
                recorder.close(LoopStatus.INTERRUPTED, str(exc) or "delivery_aborted")
            # 静默的依据是「用户已看到至少一条成功交付的分段」——零交付时
            # （如中间轮抑制 + 最终轮未及交付即中止）必须给出可见中止提示，
            # 否则用户既无正文也无通知。无记录路径没有任何 sink 交付，
            # 同样必须可见。
            aborted_silently = recorder is not None and recorder.summary().sent > 0
            return reply_result(
                "" if aborted_silently else "本次回复未确认送达，已停止后续生成。",
                llm_used=True,
                provider_id=provider.id,
                model=llm_request.model,
            )
        except LLMProviderError as exc:
            check_error_session()
            if recorder is not None:
                recorder.close(LoopStatus.FAILED, "provider_error")
            return reply_result(
                f"LLM 调用失败：{exc}",
                llm_used=True,
                provider_id=provider.id,
                model=llm_request.model,
                # 工具已产出的图片不因后续 LLM 调用失败而丢弃
                images=outbound_images_payload(tool_context),
            )
        except Exception as exc:
            check_error_session()
            if recorder is not None:
                recorder.close(LoopStatus.FAILED, "exception")
            return reply_result(
                f"LLM 调用异常：{exc}",
                llm_used=True,
                provider_id=provider.id,
                model=llm_request.model,
                images=outbound_images_payload(tool_context),
            )

        text = finalize_reply_text(
            response,
            provider_id=provider.id,
            model=llm_request.model,
            sensitive=sensitive,
            scope_key=scope_key,
            # 纯图响应不补占位文本；以外发通道实际存活图片为准——图片
            # 被限流/上限丢弃时回落占位提示，避免用户既无图又无说明。
            allow_empty=bool(tool_context.outbound_images),
        )

        # ── persistence + auto-memory dispatch + reply assembly ──────
        try:
            check_session()
            result_payload = self._persist_turn_and_build_reply(
                session=session,
                session_generation=session_generation,
                chat_id=request.chat_id,
                user_id=request.user_id,
                sender_name=request.sender_name,
                scope_key=scope_key,
                settings=settings,
                provider=provider,
                model=llm_request.model,
                text=text,
                stored_prompt=turn.stored_prompt,
                store_user_message=request.store_user_message,
                trigger_auto_memory=request.trigger_auto_memory,
                message_id=request.message_id,
                normalized_quoted_text=turn.quoted_text,
                normalized_quoted_image_urls=turn.quoted_image_urls,
                normalized_forward_text=forward_text,
                normalized_forward_image_urls=turn.forward_image_urls,
                # 落库图注只含当轮用户自己相关的三类（当前/引用/转发）；近期缓冲图是
                # 他人消息的内容，落库会把他人图注记到触发者名下且跨轮重复累积——
                # 当轮渲染仍走完整 image_descriptions（带「近期上下文图片 N」标签）
                image_descriptions=[
                    d for d in image_descriptions
                    if not d.context_label.startswith(RECENT_IMAGE_CONTEXT_PREFIX)
                ] or None,
                tool_context=tool_context,
                recorder_rows_written=recorder is not None,
            )
        except (SessionInvalidated, SessionStoreError):
            if recorder is not None:
                recorder.close(LoopStatus.INTERRUPTED, "session_invalidated")
            raise
        if recorder is not None:
            terminal_status = (
                LoopStatus.INTERRUPTED if recorder.terminal_reason else LoopStatus.COMPLETED
            )
            recorder.close(terminal_status, recorder.terminal_reason)
            self.maintain_agent_retention(scope_key)
            if recorder.final_turn_record is not None:
                result_payload = dict(result_payload)
                result_payload["agent_turn_row_id"] = recorder.final_turn_record.message_row_id
        if recorder is not None and settings.agent_delivery_final_enabled:
            # 最终轮分段模式：最终正文已由 sink 交付，reply 不再二次发送
            # （§5.1）。中间轮单开（最终轮关）时最终正文仍走旧单发路径，
            # reply 必须保留；无记录路径（同 scope 并发触发 / store 不可用）
            # 没有任何 sink 交付，reply 仍是唯一出口，置空会把整条回复静默
            # 吞掉。
            result_payload = dict(result_payload)
            result_payload["reply"] = ""
        return result_payload

    async def generate_reply(
        self,
        *,
        group_id: int | str,
        user_id: int | str,
        sender_name: str,
        prompt: str,
        delivery_sink=None,
        trigger_kind: TriggerKind | None = None,
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
        raw_user_text: str | None = None,
        store_user_message: bool = True,
        trigger_auto_memory: bool = True,
        message_id: str | None = None,
        include_recent_images: bool = False,
        mentioned_qq_ids: list[str] | None = None,
    ) -> ReplyResult:
        with usage_scope("chat", group_id=str(group_id)):
            return await self._generate_reply_for_scope(ChatTurnRequest(
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
                raw_user_text=raw_user_text,
                store_user_message=store_user_message,
                trigger_auto_memory=trigger_auto_memory,
                message_id=message_id,
                include_recent_images=include_recent_images,
                delivery_sink=delivery_sink,
                trigger_kind=trigger_kind,
                mentioned_qq_ids=mentioned_qq_ids,
            ))

    async def generate_private_reply(
        self,
        *,
        user_id: int | str,
        sender_name: str,
        prompt: str,
        delivery_sink=None,
        trigger_kind: TriggerKind | None = None,
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
        raw_user_text: str | None = None,
        store_user_message: bool = True,
        trigger_auto_memory: bool = True,
        message_id: str | None = None,
        include_recent_images: bool = False,
        mentioned_qq_ids: list[str] | None = None,
    ) -> ReplyResult:
        with usage_scope("chat"):
            return await self._generate_reply_for_scope(ChatTurnRequest(
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
                raw_user_text=raw_user_text,
                store_user_message=store_user_message,
                trigger_auto_memory=trigger_auto_memory,
                message_id=message_id,
                include_recent_images=include_recent_images,
                delivery_sink=delivery_sink,
                trigger_kind=trigger_kind,
                mentioned_qq_ids=mentioned_qq_ids,
            ))


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
            _llm_service._init_error = str(exc)
            _llm_service.config = LLMConfig(load_error=str(exc))  # type: ignore[attr-defined]
            _llm_service.vocab = VocabIndex()  # type: ignore[attr-defined]
            _llm_service._identity_repository = IdentityRepository()
            _llm_service.identities = IdentityIndex()  # type: ignore[attr-defined]
            _llm_service.identity_path = LLM_IDENTITIES_YAML_PATH  # type: ignore[attr-defined]
            _llm_service.vocab_path = LLM_VOCAB_YAML_PATH  # type: ignore[attr-defined]
            _llm_service._group_vocabs = OrderedDict()  # type: ignore[attr-defined]
            _llm_service.store = None  # type: ignore[attr-defined]
            # 闸门在 generate_reply 链路上先于 load_error 优雅返回被访问，
            # 降级实例缺这个属性会把优雅降级变成 AttributeError。
            _llm_service._scope_gate = ScopeGate()  # type: ignore[attr-defined]
    return _llm_service  # type: ignore[return-value]
