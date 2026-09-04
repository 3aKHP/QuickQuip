from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LLMToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(slots=True)
class LLMToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass(slots=True)
class LLMInlineImage:
    """Validated in-memory image bytes for one provider request only."""

    data: bytes = field(repr=False)
    media_type: str = ""
    source_label: str = ""


@dataclass(slots=True)
class LLMToolOutput:
    """Provider-neutral tool handler output before registry call metadata is added."""

    content: str
    images: list[LLMInlineImage] = field(default_factory=list)
    is_error: bool = False


@dataclass(slots=True)
class LLMConversationMessage:
    role: str
    content: str = ""
    image_urls: list[str] = field(default_factory=list)
    inline_images: list[LLMInlineImage] = field(default_factory=list)
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    is_tool_error: bool = False
    thinking_blocks: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class LLMToolResult:
    call_id: str
    name: str
    content: str
    images: list[LLMInlineImage] = field(default_factory=list)
    is_error: bool = False


@dataclass(slots=True)
class ToolManifestEntry:
    name: str
    description: str
    source: str = "builtin"
    category: str = ""
    keywords: list[str] = field(default_factory=list)
    argument_names: list[str] = field(default_factory=list)
    always_loaded: bool = False


@dataclass(slots=True)
class ToolExecutionContext:
    group_id: int | str
    user_id: int | str
    sender_name: str
    provider_id: str
    model: str
    chat_scope: str | None = None
    chat_type: str = "group"
    # 工具产出、需要直接发给用户的外发图片（与回喂模型的 images 语义相反）。
    # 每次请求新建的 context 即累加器，service 在工具循环结束后统一收进回复结果。
    outbound_images: list[LLMInlineImage] = field(default_factory=list)


# 单次回复允许携带的工具外发图片上限，防 prompt injection 驱动的刷图
MAX_OUTBOUND_TOOL_IMAGES = 3


def outbound_images_payload(context: ToolExecutionContext) -> list[str]:
    """把 context 累积的外发图片转成 base64 列表（超上限部分丢弃）。"""
    return [
        base64.b64encode(image.data).decode("ascii")
        for image in context.outbound_images[:MAX_OUTBOUND_TOOL_IMAGES]
    ]


@dataclass(slots=True)
class LLMSceneMessage:
    """A group of consecutive human messages between bot replies.

    Internal intermediate representation used during prompt assembly.
    Each scene becomes a single role="user" message at provider time,
    maintaining user/assistant alternation across all three providers.
    """

    speakers: list[dict[str, str]]
    images: list[str]
    scene_type: str  # "history", "recent", or "current"


SCENE_MARKER_CONTEXT = "【上文】"
SCENE_MARKER_CURRENT = "【当前提问】"
SCENE_MARKER_LIVE = "【现场】"
