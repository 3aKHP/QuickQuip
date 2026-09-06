"""Agent Loop 执行记录契约：身份、状态枚举、不可变 DTO 与版本化 JSON 结构。

三视图契约（§3.2）：执行记录保存已提交的生成与工具事实；重放投影保存
目标协议可用的表达；交付记录保存已计划与已尝试发送的内容。本模块只定义
数据与有限枚举，不做 I/O——持久化归 ``store_parts/agent_records.py``，
投影归 ``history_projection.py``，切分与交付状态机归 ``delivery.py``，
scope 调度归 ``service_parts/agent_runtime.py``。

所有枚举值即 SQLite 落库字符串；解析器必须拒绝未知值（§4.4），新增值
只能在版本化结构升级时引入并保持旧值可读。
"""
from __future__ import annotations

import enum
import secrets
from dataclasses import dataclass, field
from typing import Any

# 全部 agent JSON 载荷（parts/native/result/wrappers/owner）顶层 version。
AGENT_RECORD_VERSION = 1

# 单条持久化上限（§2 工程默认值；字节口径 = UTF-8）。
MAX_PERSISTED_TOOL_RESULT_BYTES = 32_768
MAX_PERSISTED_TOOL_ARGUMENT_BYTES = 32_768
MAX_NATIVE_STATE_BYTES = 262_144
MAX_LOOP_RECORD_BYTES = 8_388_608


def new_agent_id(prefix: str) -> str:
    """稳定随机 ID：前缀 + 24 hex（96 bit 熵），跨表可读可关联。"""
    return f"{prefix}_{secrets.token_hex(12)}"


class LoopStatus(enum.StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    LEGACY = "legacy"


class TriggerKind(enum.StrEnum):
    GROUP_DIRECT = "group_direct"
    GROUP_PASSIVE = "group_passive"
    PRIVATE_DIRECT = "private_direct"
    SCHEDULED_LLM = "scheduled_llm"
    BOREDOM = "boredom"
    LEGACY = "legacy"
    LEGACY_ORPHAN = "legacy_orphan"


class ToolExecutionStatus(enum.StrEnum):
    DECLARED = "declared"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"
    NOT_EXECUTED = "not_executed"


class DeliveryKind(enum.StrEnum):
    TEXT_CHUNK = "text_chunk"
    TOOL_MEDIA = "tool_media"
    HOST_NOTICE = "host_notice"


class DeliveryStatus(enum.StrEnum):
    PLANNED = "planned"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"
    SUPPRESSED = "suppressed"
    # 仅迁移可写（§4.3.5）：旧 assistant 行无 QQ ID 时标记"发送事实未保留"，
    # 不推断从未发送；运行期禁止产生该值。
    LEGACY_UNTRACKED = "legacy_untracked"


class ToolSkipReason(enum.StrEnum):
    """not_executed 终态的有限原因（§5.3/§5.4/§5.5）。"""

    ROUND_LIMIT = "limit"
    BATCH_LIMIT = "batch_limit"
    BLOCKED = "blocked"
    RECOVERY = "recovery"


class RecallStatus(enum.StrEnum):
    ACTIVE = "active"
    RECALLED = "recalled"


class DeliveryPolicy(enum.StrEnum):
    ALL_TURNS = "all_turns"
    FINAL_ONLY = "final_only"


class TextPolicy(enum.StrEnum):
    ALLOWED = "allowed"
    REPLACED_BY_FILTER = "replaced_by_filter"
    REDACTED = "redacted"


class TurnOutputStatus(enum.StrEnum):
    """Turn 普通正文的展示形态（§5.4）。"""

    VISIBLE = "visible"
    EMPTY = "empty"
    NO_VISIBLE_OUTPUT = "no_visible_output"


class ResultRetention(enum.StrEnum):
    """工具结果保留政策（§8.4）：ephemeral 结果正文禁止进入业务持久层。"""

    EPHEMERAL = "ephemeral"
    BOUNDED = "bounded"


class ResultOmissionReason(enum.StrEnum):
    SIZE_LIMIT = "size_limit"
    EPHEMERAL_POLICY = "ephemeral_policy"
    LOOP_BUDGET = "loop_budget"
    RECALL_CLEANUP = "recall_cleanup"


class ArgumentsOmissionReason(enum.StrEnum):
    SIZE_LIMIT = "size_limit"


class NativeOmissionReason(enum.StrEnum):
    SIZE_LIMIT = "size_limit"
    SENSITIVE_BLOCK = "sensitive_block"
    RECALL_CLEANUP = "recall_cleanup"
    UNSUPPORTED_STRUCTURE = "unsupported_structure"


class RecallCleanupState(enum.StrEnum):
    """撤回清理后该 Loop 的投影形态（§9.2：固定为通用档案）。"""

    CLEANED = "cleaned"


@dataclass(frozen=True, slots=True)
class ResponseOwner:
    """一次成功 provider 请求的实际归属（§7.1）。

    endpoint/profile 指纹为不可逆散列；API key、Authorization 与原始
    headers 不入库、不入日志。``display_model`` 是请求展示 model，
    ``wire_model`` 是 alias/extra_body 解析后的实际 wire model。
    """

    provider_id: str
    protocol: str
    wire_model: str
    display_model: str
    endpoint_fingerprint: str
    profile_fingerprint: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolDeclarationRecord:
    """commit_turn 时声明的工具调用（§3.1 tool_execution_id 的来源）。"""

    execution_id: str
    call_index: int
    provider_call_id: str
    tool_name: str
    arguments_json: str | None
    arguments_omission_reason: ArgumentsOmissionReason | None


@dataclass(frozen=True, slots=True)
class ToolResultRecord:
    """finish_tool 的结果载荷（§4.4 result_json 契约）。"""

    content: str
    is_error: bool
    original_bytes: int
    retained_ranges: list[tuple[int, int]] = field(default_factory=list)
    media_descriptions: list[str] = field(default_factory=list)
    status: ToolExecutionStatus = ToolExecutionStatus.SUCCEEDED


@dataclass(frozen=True, slots=True)
class ChunkPlan:
    """一个文字 Chunk 的冻结源范围（§3.3：[start,end) 对应已存正文）。"""

    chunk_index: int
    source_start: int
    source_end: int


@dataclass(frozen=True, slots=True)
class DeliveryPlanItem:
    """commit_turn 事务内写入的交付计划条目（§4.2 delivery_plan）。"""

    delivery_id: str
    kind: DeliveryKind
    turn_id: str | None = None
    tool_execution_id: str | None = None
    chunk_index: int | None = None
    source_start: int | None = None
    source_end: int | None = None
    wrappers: tuple[str, str] = ("", "")
    attachment_refs: tuple[tuple[str, int], ...] = ()
    notice_text: str | None = None


@dataclass(frozen=True, slots=True)
class TurnResponseRecord:
    """commit_turn 的模型响应输入（§5.3 步骤 4-5：已过滤、已冻结）。"""

    text: str
    text_policy: TextPolicy
    output_status: TurnOutputStatus
    finish_reason: str | None
    parts: tuple[dict[str, Any], ...] = ()
    native_state: dict[str, Any] | None = None
    native_omission_reason: NativeOmissionReason | None = None
    owner: ResponseOwner | None = None


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """一次交付尝试的回执（§6.2：仅可信成功回执归 sent）。"""

    status: DeliveryStatus
    message_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class DeliverySummary:
    """Loop 关闭时的交付归纳（§5.1 AgentLoopResult.delivery_summary）。"""

    total: int = 0
    sent: int = 0
    failed: int = 0
    unknown: int = 0
    skipped: int = 0
    suppressed: int = 0


@dataclass(frozen=True, slots=True)
class AgentLoopResult:
    """生成入口的统一返回（§5.1）。已发送内容不再作为 reply 二次发送。"""

    loop_id: str
    status: LoopStatus
    delivery_summary: DeliverySummary
    rule_name: str
    rate_limit_key: str
    provider_id: str
    model: str
    terminal_reason: str | None = None
    # final_only 模式下仍由适配层单次发送的最终正文；空 = 全部经 sink 交付。
    final_text: str = ""
    # 关闭开关时随最终文字交付的工具图片（base64 列表，§6.3）。
    final_images: tuple[str, ...] = ()
