from __future__ import annotations

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
class LLMConversationMessage:
    role: str
    content: str = ""
    image_urls: list[str] = field(default_factory=list)
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
    is_error: bool = False


@dataclass(slots=True)
class ToolExecutionContext:
    group_id: int | str
    user_id: int | str
    sender_name: str
    provider_id: str
    model: str
    chat_scope: str | None = None
    chat_type: str = "group"


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
