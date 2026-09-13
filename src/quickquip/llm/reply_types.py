"""``generate_reply`` 族的输入/输出类型契约（纯 typing + 纯数据模块）。

``llm/service.py`` 的公共入口签名与其消费者（chat/awakening 等）共用同
一份形状定义，不再各自建模宽 dict 或三层穿透同名形参。无运行时依赖。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from quickquip.llm.agent_records import TriggerKind


class ReplyResult(TypedDict, total=False):
    """``LLMService.generate_reply`` / ``generate_private_reply`` 的返回契约。

    键集按路径漂移是既有契约——短路/错误路径只含基础四键
    （reply / rate_limit_key / rule_name / llm_used），成功路径携带
    provider_id / model / images / scope_key，agent 记录路径另含
    agent_turn_row_id；「reply 为空字符串」表示正文已由逐 Turn 交付
    sink 送出（docs/dev/llm-module.md §5.1）。
    """

    reply: str
    rate_limit_key: str
    rule_name: str
    llm_used: bool
    provider_id: str
    model: str
    images: list[str]
    scope_key: str
    agent_turn_row_id: int


@dataclass(slots=True)
class ChatTurnRequest:
    """一次聊天回复生成的完整输入（群聊/私聊共用，chat_type 区分）。

    公共入口（``generate_reply`` / ``generate_private_reply``）保持关键字
    签名不变、在本结构上收敛一次，主链（``_generate_reply_for_scope``）
    只消费本结构——消除三层 24 形参穿透。
    """

    chat_id: int | str
    chat_type: str
    user_id: int | str
    sender_name: str
    prompt: str
    image_urls: list[str] | None = None
    recent_messages: list[dict[str, str]] | None = None
    quoted_text: str = ""
    quoted_image_urls: list[str] | None = None
    quoted_sender_name: str = ""
    quoted_user_id: str = ""
    quoted_is_bot_self: bool = False
    forward_text: str = ""
    forward_image_urls: list[str] | None = None
    voice_text: str = ""
    raw_user_text: str | None = None
    store_user_message: bool = True
    trigger_auto_memory: bool = True
    message_id: str | None = None
    include_recent_images: bool = False
    delivery_sink: Any = None
    trigger_kind: "TriggerKind | None" = None
    mentioned_qq_ids: list[str] | None = None
