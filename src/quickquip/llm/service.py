"""
LLM Service — framework-agnostic core.

Moved from ``plugins/llm_runtime.py`` so that the business logic lives
inside ``quickquip/`` with no NoneBot2 dependency.  The NoneBot2 plugin
layer now re-exports from here via ``plugins/llm_runtime.py``.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime
import logging
from pathlib import Path
import re
from typing import Any, TYPE_CHECKING
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.common.sensitive_filter import (
    DEFAULT_BLOCK_REPLY,
    DEFAULT_OUTPUT_FALLBACK,
    SCRUB_PLACEHOLDER,
    SensitiveFilter,
    get_filter as _get_sensitive_filter,
    log_hits as _log_sensitive_hits,
    reload_filter as _reload_sensitive_filter,
    scan_and_log as _scan_sensitive_text,
)
from quickquip.llm.config import (
    DISABLED_PROVIDER_REPLY,
    LLMConfig,
    PersonaConfig,
    ProviderConfig,
    load_llm_config,
    load_personas_only,
    provider_builtin_search_active,
)
from quickquip.llm.rendering import append_web_search_source_block
from quickquip.sts.config import (
    DEFECTIFY_RATE_LIMIT_KEY,
    DEFECTIFY_RULE_NAME,
    TURMFLUCH_RATE_LIMIT_KEY,
    TURMFLUCH_RULE_NAME,
)
from quickquip.sts.formulas.card_le.parsing import extract_card_le_name
from quickquip.sts.formulas.card_le.prompting import build_turmfluch_prompt
from quickquip.sts.formulas.defectify.prompting import build_defectify_prompt
from quickquip.llm.identity import IdentityIndex
from quickquip.llm.image_preprocessor import ImageDescription, ImagePreprocessor
from quickquip.llm.image_routing import (
    IMAGE_PREPROCESSING_FAILED_REPLY,
    IMAGE_PREPROCESSING_UNAVAILABLE_REPLY,
    match_image_descriptions,
    plan_non_vision_images,
)
from quickquip.llm.mcp import MCPClientManager
from quickquip.llm.prompting import (
    build_messages,
    build_system_prompt,
    build_turn_envelope,
    merge_image_urls,
)
from quickquip.llm.token_estimate import estimate_tokens
from quickquip.llm.epoch import (
    DEFAULT_EPOCH_MAX_ROWS,
    EpochKey,
    EpochManager,
    EpochParams,
    estimate_rows_budget,
)
from quickquip.llm.provider import (
    LLMProviderError,
    LLMRequest,
    build_provider_client,
    strip_leading_reasoning_content,
)
from quickquip.llm.quick_judge import (
    QuickJudgeResult as QuickJudgeResult,  # noqa: F401 — re-exported for callers/tests
    run_quick_judge,
    run_quick_judge_detailed,
)
from quickquip.llm.service_parts.constants import (
    DEFAULT_ENABLED_TOOLS as DEFAULT_ENABLED_TOOLS,  # noqa: F401 — re-exported via plugins/llm_runtime
    MAX_MEMORY_RETRIEVAL_ITEMS,
    MAX_STORED_CONVERSATION_MESSAGES,
    MAX_STORED_MEMORY_ITEMS as MAX_STORED_MEMORY_ITEMS,  # noqa: F401 — re-exported via plugins/llm_runtime
    MAX_TRIGGER_CONTEXT_MESSAGES,
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
    McpLifecycleMixin,
    ScheduleMessagesToolMixin,
    ScopeMixin,
    StateMixin,
    ToolMixin,
)
from quickquip.llm.usage import envelope_meter, epoch_meter, media_meter, usage_scope
from quickquip.llm.settings import ResolvedGroupSettings, resolve_group_settings
from quickquip.llm.single_shot import (
    CommandSingleShotSpec,
    run_card_le_nearest,
    run_command_single_shot,
)
from quickquip.llm.store import LLMStore
from quickquip.llm.tool_registry import ToolRegistry
from quickquip.llm.tool_loop import run_tool_call_loop
from quickquip.llm.tools import (
    LLMConversationMessage,
    LLMToolSpec,
    ToolExecutionContext,
    outbound_images_payload,
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
MAX_QUOTED_MESSAGE_CHARS = 1200
MAX_PERSISTED_IMAGE_DESC_CHARS = 200
MAX_PERSISTED_IMAGE_DESC_BLOB_CHARS = 800
_GROUP_CACHE_MAX = 512


logger = logging.getLogger(__name__)


def _defectify_reply_text(raw_text: str) -> str | None:
    return raw_text or None


def _turmfluch_reply_text(raw_text: str) -> str | None:
    name = extract_card_le_name(raw_text)
    if name is None:
        return None
    return f"{name}了"


# 一次性生成入口的差异点束；共享管线本体在 quickquip.llm.single_shot
_DEFECTIFY_SPEC = CommandSingleShotSpec(
    rate_limit_key=DEFECTIFY_RATE_LIMIT_KEY,
    rule_name=DEFECTIFY_RULE_NAME,
    usage_reply="用法：/defectify <文字>，也可以在命令里附图，或引用一条消息/图片后直接发送 /defectify。",
    invalid_reply="模型没有返回可显示的文本。",
    temperature=0.9,
    input_channel="defectify_input",
    output_channel="defectify_output",
    usage_scope_name="defectify",
    prompt_builder=build_defectify_prompt,
    response_parser=_defectify_reply_text,
)
_TURMFLUCH_SPEC = CommandSingleShotSpec(
    rate_limit_key=TURMFLUCH_RATE_LIMIT_KEY,
    rule_name=TURMFLUCH_RULE_NAME,
    usage_reply="用法：/turmfluch <文字>，也可以在命令里附图，或引用一条消息/图片后直接发送 /turmfluch。",
    invalid_reply="模型没有返回合法的卡牌/遗物名。",
    temperature=0.7,
    input_channel="turmfluch_input",
    output_channel="turmfluch_output",
    usage_scope_name="turmfluch",
    prompt_builder=build_turmfluch_prompt,
    response_parser=_turmfluch_reply_text,
    log_label="/turmfluch",
)


@dataclass
class _ImagePreprocessingOutcome:
    """图像预处理段继续走主生成链路时向调用方回传的状态。"""

    effective_image_urls: list[str]
    request_quoted_image_urls: list[str]
    request_forward_image_urls: list[str]
    image_descriptions: list[ImageDescription]
    is_non_vision: bool


def _image_caption_blob(descriptions: list[ImageDescription]) -> tuple[int, str]:
    """图注落库文本：单条截 200、整坨截 800，顺序 = 候选顺序（确定性）。

    截断必须在落库前完成——落库字节即前缀字节，下一轮换侧 history 原样复现。
    """
    descs = [d.text_description.strip() for d in descriptions if d.text_description.strip()]
    blob = "；".join(d[:MAX_PERSISTED_IMAGE_DESC_CHARS].rstrip() for d in descs)
    return len(descs), blob[:MAX_PERSISTED_IMAGE_DESC_BLOB_CHARS]


class LLMService(ScopeMixin, ToolMixin, McpLifecycleMixin, DrawSvgToolMixin, ScheduleMessagesToolMixin, HealthMixin, StateMixin, AutoMemoryMixin):
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
        self._init_mcp_lifecycle()
        self._session_presets: dict[str, str] = {}
        # 会话纪元锚点表（进程内）：进程重启 = 冷一次缓存，首请求按 CTX 跨度懒初始化
        self._epochs = EpochManager()
        self._init_auto_memory()
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

        self._group_vocabs: OrderedDict[str, VocabIndex] = OrderedDict()
        self._group_identities: OrderedDict[str, IdentityIndex] = OrderedDict()

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
        if len(self._group_identities) >= _GROUP_CACHE_MAX:
            self._group_identities.popitem(last=False)
        self._group_identities[cache_key] = merged
        return merged

    def group_identities(self, group_id: str) -> IdentityIndex:
        """按群返回合并后的身份索引，供装配层等外部调用方使用。"""
        return self._resolve_identities(group_id)

    def reload_config(self) -> LLMConfig:
        self.config = load_llm_config(self.config_path)
        _reload_sensitive_filter()
        self.rebuild_image_preprocessor()
        self.vocab = VocabIndex.from_file(self.vocab_path)
        self.identities = IdentityIndex.from_file(self.identity_path)
        self._group_vocabs.clear()
        self._group_identities.clear()
        self.mark_mcp_dirty()
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
            tool_discovery_enabled=self._is_tool_discovery_enabled(chat_type, provider_id=provider_id),
            tool_search_name=TOOL_SEARCH_NAME,
            tool_list_name=TOOL_LIST_NAME,
            deferred_tool_categories=self._get_deferred_tool_categories(chat_type, provider_id=provider_id),
            chat_type=chat_type,
            provider_style_overrides=provider_style_overrides,
            session_preset=session_preset,
        )

    def _build_turn_envelope(
        self,
        group_id: int | str,
        chat_type: str,
        prompt: str,
        memories: list[dict[str, object]],
        participants: list[dict[str, str]] | None = None,
    ) -> str:
        # 时钟唯一注入点：信封以外的 prompt 组装全链路无时钟。
        return build_turn_envelope(
            now=datetime.now(ZoneInfo(BEIJING_TIMEZONE)),
            prompt=prompt,
            memories=memories,
            vocab=self._resolve_vocab(str(group_id)),
            chat_type=chat_type,
            participants=participants,
        )

    async def quick_judge(self, prompt: str, max_tokens: int = 64) -> str:
        """
        用于 context_rules 和 awakening 的极速判定调用。
        不走群配置、不注入记忆、不启用工具，只发单条 system+user。
        优先使用 [triggers.quick_judge] 配置的 provider/model。
        """
        # 薄委托：通道本体在 quickquip.llm.quick_judge。显式传本模块级
        # build_provider_client，保持既有 patch 点有效，且不向通道传递 self。
        return await run_quick_judge(
            self.config, prompt, max_tokens, client_builder=build_provider_client
        )

    async def quick_judge_detailed(self, prompt: str, max_tokens: int = 64) -> QuickJudgeResult:
        """``quick_judge`` 的结构化内部通道：按结果类别返回诊断字段，
        不抛 provider 异常。诊断只含 provider/model/类别/finish reason/
        token/耗时，禁止携带 prompt、模型原始响应、凭据或 endpoint。"""
        return await run_quick_judge_detailed(
            self.config, prompt, max_tokens, client_builder=build_provider_client
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
        turn_envelope: str = "",
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
            include_recent_images=include_recent_images,
            turn_envelope=turn_envelope,
        )

    async def generate_defectify_reply(
        self,
        *,
        chat_id: int | str,
        chat_type: str,
        prompt: str,
        image_urls: list[str] | None = None,
        quoted_text: str = "",
        quoted_image_urls: list[str] | None = None,
        quoted_sender_name: str = "",
        quoted_user_id: str = "",
    ) -> dict[str, str]:
        # 薄编排：管线本体在 quickquip.llm.single_shot。显式传本模块级
        # build_provider_client / _get_sensitive_filter，保持既有 patch 点有效。
        return await run_command_single_shot(
            spec=_DEFECTIFY_SPEC,
            config=self.config,
            chat_id=chat_id,
            resolve_scope_key=lambda: self.build_chat_scope_key(chat_id, chat_type),
            resolve_settings=lambda: self.get_chat_settings(chat_id, chat_type=chat_type),
            get_sensitive=_get_sensitive_filter,
            client_builder=build_provider_client,
            merge_image_urls=self._merge_image_urls,
            prompt=prompt,
            image_urls=image_urls,
            quoted_text=quoted_text,
            quoted_image_urls=quoted_image_urls,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
        )

    async def generate_turmfluch_reply(
        self,
        *,
        chat_id: int | str,
        chat_type: str,
        prompt: str,
        image_urls: list[str] | None = None,
        quoted_text: str = "",
        quoted_image_urls: list[str] | None = None,
        quoted_sender_name: str = "",
        quoted_user_id: str = "",
    ) -> dict[str, Any]:
        """/turmfluch 命令：把输入提炼成一句「<卡牌或遗物名>了」。"""
        # 薄编排：同 generate_defectify_reply，管线本体在 quickquip.llm.single_shot。
        return await run_command_single_shot(
            spec=_TURMFLUCH_SPEC,
            config=self.config,
            chat_id=chat_id,
            resolve_scope_key=lambda: self.build_chat_scope_key(chat_id, chat_type),
            resolve_settings=lambda: self.get_chat_settings(chat_id, chat_type=chat_type),
            get_sensitive=_get_sensitive_filter,
            client_builder=build_provider_client,
            merge_image_urls=self._merge_image_urls,
            prompt=prompt,
            image_urls=image_urls,
            quoted_text=quoted_text,
            quoted_image_urls=quoted_image_urls,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
        )

    async def generate_card_le_nearest(
        self,
        *,
        captured: str,
        chat_id: int | str,
        chat_type: str,
    ) -> dict | None:
        """被动路径：群友说的「{captured}了」里的 captured 不是合法名时，找最近的
        真名，返回 ``{"reply": "名了", ...}``；无合法结果返回 None。

        走 ``[triggers.quick_judge]`` 配置的专用便宜模型，不走群主模型。
        """
        # 薄编排：管线本体在 quickquip.llm.single_shot，patch 点同上。
        return await run_card_le_nearest(
            config=self.config,
            chat_id=chat_id,
            resolve_scope_key=lambda: self.build_chat_scope_key(chat_id, chat_type),
            get_sensitive=_get_sensitive_filter,
            client_builder=build_provider_client,
            captured=captured,
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
            tool_discovery_enabled=self._is_tool_discovery_enabled(context.chat_type, provider_id=provider.id),
            tool_search_name=TOOL_SEARCH_NAME,
            tool_list_name=TOOL_LIST_NAME,
            enabled_tool_names=self._get_enabled_tool_names(chat_type=context.chat_type, provider_id=provider.id),
            initial_tool_names=[spec.name for spec in request.tools],
            tool_discovery_search_limit=self.config.tools.discovery_search_limit,
            tool_discovery_max_loaded_tools=self.config.tools.discovery_max_loaded_tools,
            image_preprocessor=self.image_preprocessor,
        )

    async def _preprocess_images_for_model(
        self,
        *,
        chat_id: int | str,
        scope_key: str,
        provider: ProviderConfig,
        settings: ResolvedGroupSettings,
        request_image_urls: list[str],
        request_quoted_image_urls: list[str],
        request_forward_image_urls: list[str],
        normalized_image_urls: list[str],
        normalized_quoted_image_urls: list[str],
        normalized_forward_image_urls: list[str],
        recent_messages: list[dict[str, str]] | None,
        include_recent_images: bool,
        sensitive: SensitiveFilter,
    ) -> dict[str, object] | _ImagePreprocessingOutcome:
        # ── image preprocessing & non-VLM stripping ──────────────────
        current_model = settings.model or provider.default_model
        is_non_vision = current_model in provider.non_vision_models
        # 转发图片不作为媒体本体附带（媒体本体永不进前缀），仅以文本/图注形式出现
        effective_image_urls = merge_image_urls(request_image_urls, request_quoted_image_urls)

        image_plan = None
        if is_non_vision:
            image_plan = plan_non_vision_images(
                image_urls=request_image_urls,
                quoted_image_urls=request_quoted_image_urls,
                forward_image_urls=request_forward_image_urls,
                recent_messages=recent_messages,
                include_recent_images=include_recent_images,
                max_trigger_context_messages=MAX_TRIGGER_CONTEXT_MESSAGES,
            )
            if image_plan.error_reply:
                return {
                    "reply": image_plan.error_reply,
                    "rate_limit_key": LLM_RULE_NAME,
                    "rule_name": LLM_RULE_NAME,
                    "llm_used": False,
                }

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

        image_descriptions: list[ImageDescription] = []
        ok_count = 0
        if image_plan is not None and image_plan.candidates:
            if self.image_preprocessor is None:
                logger.error(
                    "group=%s model=%s requires image preprocessing but no preprocessor is bound",
                    chat_id,
                    current_model,
                )
                return {
                    "reply": IMAGE_PREPROCESSING_UNAVAILABLE_REPLY,
                    "rate_limit_key": LLM_RULE_NAME,
                    "rule_name": LLM_RULE_NAME,
                    "llm_used": False,
                    "provider_id": provider.id,
                    "model": current_model,
                }

            raw_descriptions = await self.image_preprocessor.describe_images(
                [candidate.url for candidate in image_plan.candidates]
            )
            description_match = match_image_descriptions(
                image_plan.candidates,
                raw_descriptions,
            )
            image_descriptions = description_match.descriptions
            ok_count = len(image_descriptions)
            if description_match.failed_urls:
                logger.warning(
                    "group=%s preprocessor: %d ok, %d failed (%s)",
                    chat_id,
                    ok_count,
                    len(description_match.failed_urls),
                    ", ".join(description_match.failed_urls),
                )
                return {
                    "reply": IMAGE_PREPROCESSING_FAILED_REPLY,
                    "rate_limit_key": LLM_RULE_NAME,
                    "rule_name": LLM_RULE_NAME,
                    "llm_used": True,
                    "provider_id": self.config.image_preprocessing.provider_id,
                    "model": self.config.image_preprocessing.model,
                }
            description_blob = "\n".join(
                item.text_description for item in image_descriptions
                if item.text_description
            )
            description_scan = _scan_sensitive_text(
                description_blob,
                channel="image_description",
                scope=scope_key,
                sensitive_filter=sensitive,
            )
            if description_scan.blocked:
                return {
                    "reply": DEFAULT_BLOCK_REPLY,
                    "rate_limit_key": LLM_RULE_NAME,
                    "rule_name": LLM_RULE_NAME,
                    "llm_used": True,
                    "provider_id": self.config.image_preprocessing.provider_id,
                    "model": self.config.image_preprocessing.model,
                }
            logger.info("group=%s preprocessor: all %d images described", chat_id, ok_count)

        if image_plan is not None and image_plan.candidates:
            stripped_count = len(image_plan.candidates)
            logger.info(
                "group=%s non-VLM strip: replaced %d images with text descriptions",
                chat_id,
                stripped_count,
            )
            effective_image_urls = []
            request_image_urls = []
            request_quoted_image_urls = []
            request_forward_image_urls = []

        # ── end image preprocessing ─────────────────────────────────
        return _ImagePreprocessingOutcome(
            effective_image_urls=effective_image_urls,
            request_quoted_image_urls=request_quoted_image_urls,
            request_forward_image_urls=request_forward_image_urls,
            image_descriptions=image_descriptions,
            is_non_vision=is_non_vision,
        )

    def _load_scrubbed_history_and_participants(
        self,
        *,
        chat_id: int | str,
        scope_key: str,
        settings: ResolvedGroupSettings,
        sensitive: SensitiveFilter,
        user_id: int | str,
        sender_name: str,
        recent_messages: list[dict[str, str]] | None,
        quoted_sender_name: str,
        quoted_user_id: str,
        epoch_key: EpochKey,
        epoch_params: EpochParams,
    ) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
        # 会话纪元读取：只追加锚点窗口（懒初始化/冷场/触顶/行数兜底的推进判定
        # 全部在 EpochManager 内），纪元内前缀逐字节稳定。auto_memory 仍走
        # list_recent_conversation_messages 的 DESC LIMIT 尾读——两个消费者
        # 两种读模式，勿在此"统一"。
        self._epochs.maybe_advance(epoch_key, store=self.store, params=epoch_params)
        anchor = self._epochs.current_anchor(epoch_key) or 0
        if settings.history_limit is not None:
            # 显式 /llm context_limit 覆盖：尊重"更小窗口"意图，退化为该会话的
            # 行数兜底滚动窗（每轮按行数重新锚定）。
            backstop = self.store.find_anchor_row_id_by_rows(scope_key, settings.history_limit)
            if backstop is not None:
                anchor = max(anchor, backstop)
        history = self.store.list_conversation_messages_since(
            scope_key, anchor, limit=DEFAULT_EPOCH_MAX_ROWS,
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
        return history, participants

    def _persist_turn_and_build_reply(
        self,
        *,
        chat_id: int | str,
        user_id: int | str,
        sender_name: str,
        scope_key: str,
        settings: ResolvedGroupSettings,
        provider: ProviderConfig,
        model: str,
        text: str,
        stored_prompt: str,
        store_user_message: bool,
        message_id: str | None,
        normalized_quoted_text: str,
        normalized_quoted_image_urls: list[str],
        normalized_forward_text: str,
        normalized_forward_image_urls: list[str],
        image_descriptions: list[ImageDescription] | None = None,
        tool_context: ToolExecutionContext,
    ) -> dict[str, object]:
        current_identity = self._resolve_identities(str(chat_id)).resolve_user(user_id, sender_name)
        if store_user_message:
            raw_turn_parts: list[str] = []
            if normalized_quoted_text or normalized_quoted_image_urls:
                q_text = normalized_quoted_text or f"[图片 {len(normalized_quoted_image_urls)} 张]"
                q_suffix = f" [附图 {len(normalized_quoted_image_urls)} 张]" if normalized_quoted_image_urls else ""
                raw_turn_parts.append(f"[引用] {q_text}{q_suffix}")
            if normalized_forward_text or normalized_forward_image_urls:
                fw_text = normalized_forward_text or "[合并转发消息]"
                fw_suffix = f" [附图 {len(normalized_forward_image_urls)} 张]" if normalized_forward_image_urls else ""
                raw_turn_parts.append(fw_text + fw_suffix)
            if image_descriptions:
                # 非 VLM 路径：图注以文本身份落库（媒体本体永不进前缀）；
                # 下一轮换侧 history 直接复用落库字节，转述内容不再随轮丢失
                caption_count, caption_blob = _image_caption_blob(image_descriptions)
                if caption_count:
                    raw_turn_parts.append(f"[图片 {caption_count} 张：{caption_blob}]")
            raw_turn_parts.append(stored_prompt)
            raw_turn = "\n".join(raw_turn_parts)
            self.store.append_conversation_message(
                scope_key,
                user_id,
                "user",
                stored_prompt,
                sender_name=sender_name,
                canonical_name=current_identity.canonical_name,
                message_id=str(message_id) if message_id else None,
                raw_content=raw_turn,
            )
        self.store.append_conversation_message(scope_key, None, "assistant", text)
        # 纪元裁剪：floor = 该 scope 所有纪元键的最老锚点（None = 只按硬上限兜底，
        # 绝不按窗口重估删行——重启后懒初始化还要读旧行）
        self.store.crop_conversation_messages(
            scope_key,
            floor_id=self._epochs.oldest_anchor(scope_key),
            keep_last=MAX_STORED_CONVERSATION_MESSAGES,
        )

        if store_user_message and settings.auto_memory_enabled and settings.memory_enabled:
            asyncio.create_task(
                self._extract_auto_memory(
                    scope_key=scope_key,
                    user_id=user_id,
                    sender_name=sender_name,
                    canonical_name=current_identity.canonical_name,
                    user_text=stored_prompt,
                    assistant_text=text,
                    persona_id=settings.persona_id,
                )
            )

        return {
            "reply": text,
            "rate_limit_key": LLM_RULE_NAME,
            "rule_name": LLM_RULE_NAME,
            "llm_used": True,
            "provider_id": provider.id,
            "model": model,
            # 工具外发图片（base64 PNG），适配层拼在文本后发送；上限见 MAX_OUTBOUND_TOOL_IMAGES
            "images": outbound_images_payload(tool_context),
        }

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
        raw_user_text: str | None = None,
        store_user_message: bool = True,
        message_id: str | None = None,
        include_recent_images: bool = False,
    ) -> dict[str, object]:
        prompt = prompt.strip()
        normalized_raw_user_text = None if raw_user_text is None else raw_user_text.strip()
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
        stored_prompt = (
            normalized_raw_user_text if normalized_raw_user_text is not None else prompt
        )[: self.config.runtime.max_prompt_chars]

        if not prompt and not normalized_quoted_text and not normalized_image_urls and not normalized_quoted_image_urls and not normalized_forward_text and not normalized_forward_image_urls:
            return {
                "reply": self.config.triggers.empty_prompt_reply,
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
                "llm_used": False,
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
                    "llm_used": False,
                }

        if self.config.load_error:
            return {
                "reply": f"LLM 配置不可用：{self.config.load_error}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
                "llm_used": False,
            }

        settings = self.get_chat_settings(chat_id, chat_type=chat_type)
        if not settings.enabled:
            return {
                "reply": f"{self._scope_subject(chat_type)} LLM 已关闭。",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
                "llm_used": False,
            }

        provider = self.config.providers.get(settings.provider_id)
        if provider is None:
            return {
                "reply": f"当前 provider 不存在：{settings.provider_id}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
                "llm_used": False,
            }
        if not provider.enabled:
            return {
                "reply": DISABLED_PROVIDER_REPLY.format(provider_id=settings.provider_id),
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
                "llm_used": False,
            }

        persona = self.config.personas.get(settings.persona_id)
        if persona is None:
            return {
                "reply": f"当前 persona 不存在：{settings.persona_id}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
                "llm_used": False,
            }

        trimmed_prompt = prompt[: self.config.runtime.max_prompt_chars]
        quoted_prompt = normalized_quoted_text[:MAX_QUOTED_MESSAGE_CHARS]
        analysis_prompt = "\n".join(
            item for item in [stored_prompt, quoted_prompt] if item
        )[: self.config.runtime.max_prompt_chars]

        # ── image preprocessing & non-VLM stripping ──────────────────
        image_outcome = await self._preprocess_images_for_model(
            chat_id=chat_id,
            scope_key=scope_key,
            provider=provider,
            settings=settings,
            request_image_urls=request_image_urls,
            request_quoted_image_urls=request_quoted_image_urls,
            request_forward_image_urls=request_forward_image_urls,
            normalized_image_urls=normalized_image_urls,
            normalized_quoted_image_urls=normalized_quoted_image_urls,
            normalized_forward_image_urls=normalized_forward_image_urls,
            recent_messages=recent_messages,
            include_recent_images=include_recent_images,
            sensitive=sensitive,
        )
        if isinstance(image_outcome, dict):
            return image_outcome
        effective_image_urls = image_outcome.effective_image_urls
        request_quoted_image_urls = image_outcome.request_quoted_image_urls
        request_forward_image_urls = image_outcome.request_forward_image_urls
        image_descriptions = image_outcome.image_descriptions
        is_non_vision = image_outcome.is_non_vision
        # ── end image preprocessing ─────────────────────────────────
        # 转发图注并入 normalized_forward_text：当轮渲染（_build_messages）与落库
        # （_persist_turn_and_build_reply）共用同一变量，两条路径字节一致；
        # 并入后从 image_descriptions 摘除，避免视觉转述行与落库 caption 双重出现
        forward_descs = [d for d in image_descriptions if d.context_label.startswith("转发消息图片")]
        if forward_descs:
            forward_caption_count, forward_caption_blob = _image_caption_blob(forward_descs)
            if forward_caption_count:
                normalized_forward_text = "\n".join(
                    part
                    for part in (
                        normalized_forward_text,
                        f"[转发图片 {forward_caption_count} 张：{forward_caption_blob}]",
                    )
                    if part
                )
                image_descriptions = [d for d in image_descriptions if not d.context_label.startswith("转发消息图片")]
        # ── history load + sensitive scrub + participants ────────────
        epoch_key = EpochKey(
            scope_key=scope_key,
            provider_id=provider.id,
            model=settings.model or provider.default_model,
        )
        history, participants = self._load_scrubbed_history_and_participants(
            chat_id=chat_id,
            scope_key=scope_key,
            settings=settings,
            sensitive=sensitive,
            user_id=user_id,
            sender_name=sender_name,
            recent_messages=recent_messages,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
            epoch_key=epoch_key,
            epoch_params=self.config.resolve_epoch_params(provider),
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

        builtin_search_active = provider_builtin_search_active(provider)
        tool_specs = (
            self._get_enabled_tool_specs(chat_type=chat_type, provider_id=provider.id)
            if self.config.runtime.tool_calling_enabled
            else []
        )
        session_preset = self.get_session_preset(scope_key) if chat_type == "private" else ""
        system_prompt = self._build_system_prompt(
            persona,
            chat_id,
            chat_type,
            tool_specs,
            provider_style_overrides=provider.style_overrides,
            session_preset=session_preset,
            provider_id=provider.id,
            builtin_search_active=builtin_search_active,
        )
        turn_envelope = self._build_turn_envelope(
            chat_id,
            chat_type,
            analysis_prompt or trimmed_prompt,
            memories,
            participants=participants,
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
            include_recent_images=include_recent_images and not is_non_vision,
            turn_envelope=turn_envelope,
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
            builtin_search=builtin_search_active,
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
            # 拿到群级 persona 后把聊天主链路升级为带人格归因的 scope；
            # scope 生命周期与 provider 调用同处一个函数，退出即复位。
            # group_id 用 scope_key（群聊 = str(chat_id)，私聊 = private:{id}），
            # 与 auto_memory 等派生调用的归因口径一致。
            with (
                usage_scope("chat", group_id=scope_key, persona_id=settings.persona_id or None),
                envelope_meter(estimate_tokens(turn_envelope)),
                epoch_meter(estimate_rows_budget(history)),
                # 媒体账本：当轮实际随请求附带的图片数（只有末条 user 消息携带
                # image_urls；非 VLM 剥离后恒 0，0 也是有效信号）
                media_meter(len(messages[-1].image_urls)),
            ):
                # 只有请求才续期 provider 侧缓存；失败请求也可能已写缓存，保守续期
                self._epochs.note_activity(epoch_key)
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
                "llm_used": True,
                "provider_id": provider.id,
                "model": request.model,
                # 工具已产出的图片不因后续 LLM 调用失败而丢弃
                "images": outbound_images_payload(tool_context),
            }
        except Exception as exc:
            return {
                "reply": f"LLM 调用异常：{exc}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
                "llm_used": True,
                "provider_id": provider.id,
                "model": request.model,
                "images": outbound_images_payload(tool_context),
            }

        text = strip_leading_reasoning_content(response.text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text:
            text = "模型没有返回可显示的文本。"

        if response.web_search is not None:
            logger.info(
                "LLM built-in web search: provider=%s model=%s queries=%s sources=%s",
                provider.id,
                request.model,
                response.web_search.queries,
                [source.url for source in response.web_search.sources],
            )
            text = append_web_search_source_block(text, response.web_search)

        if sensitive.is_loaded:
            output_scan = sensitive.scan(text)
            if output_scan.hits:
                _log_sensitive_hits("output", scope_key, output_scan)
            if output_scan.blocked:
                # Don't write the blocked output to history — that would
                # poison the next turn's context. Substitute the fallback
                # for both the user-visible reply and what we persist.
                text = DEFAULT_OUTPUT_FALLBACK

        # ── persistence + auto-memory dispatch + reply assembly ──────
        return self._persist_turn_and_build_reply(
            chat_id=chat_id,
            user_id=user_id,
            sender_name=sender_name,
            scope_key=scope_key,
            settings=settings,
            provider=provider,
            model=request.model,
            text=text,
            stored_prompt=stored_prompt,
            store_user_message=store_user_message,
            message_id=message_id,
            normalized_quoted_text=normalized_quoted_text,
            normalized_quoted_image_urls=normalized_quoted_image_urls,
            normalized_forward_text=normalized_forward_text,
            normalized_forward_image_urls=normalized_forward_image_urls,
            image_descriptions=image_descriptions or None,
            tool_context=tool_context,
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
        quoted_is_bot_self: bool = False,
        forward_text: str = "",
        forward_image_urls: list[str] | None = None,
        voice_text: str = "",
        raw_user_text: str | None = None,
        store_user_message: bool = True,
        message_id: str | None = None,
        include_recent_images: bool = False,
    ) -> dict[str, object]:
        with usage_scope("chat", group_id=str(group_id)):
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
                raw_user_text=raw_user_text,
                store_user_message=store_user_message,
                message_id=message_id,
                include_recent_images=include_recent_images,
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
        raw_user_text: str | None = None,
        store_user_message: bool = True,
        message_id: str | None = None,
        include_recent_images: bool = False,
    ) -> dict[str, object]:
        with usage_scope("chat"):
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
                raw_user_text=raw_user_text,
                store_user_message=store_user_message,
                message_id=message_id,
                include_recent_images=include_recent_images,
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
            _llm_service._init_error = str(exc)
            _llm_service.config = LLMConfig(load_error=str(exc))  # type: ignore[attr-defined]
            _llm_service.vocab = VocabIndex()  # type: ignore[attr-defined]
            _llm_service.identities = IdentityIndex()  # type: ignore[attr-defined]
            _llm_service.store = None  # type: ignore[attr-defined]
    return _llm_service  # type: ignore[return-value]
