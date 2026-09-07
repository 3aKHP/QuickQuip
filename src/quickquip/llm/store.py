"""LLMStore：LLM 对话/记忆/归档/群设置的 SQLite 持久化层。

历史上市一个 645 行的单类，现按业务域拆分到 ``store_parts/`` 子包：
- 基础设施（连接/schema/守卫）→ ``_StoreBase``
- 会话消息 → ``ConversationStoreMixin``
- 长期记忆 → ``MemoryStoreMixin``
- 私聊归档 → ``SessionArchiveMixin``
- 群设置覆盖 → ``GroupSettingsMixin``
- Agent 执行记录 → ``AgentRecordsStoreMixin``

对外 import 路径不变：``from quickquip.llm.store import LLMStore, GroupSettingsOverride``。
"""

from __future__ import annotations

from quickquip.llm.store_parts._base import GroupSettingsOverride as GroupSettingsOverride  # noqa: F401
from quickquip.llm.store_parts._base import _StoreBase
from quickquip.llm.store_parts._base import _build_query_tokens as _build_query_tokens  # noqa: F401
from quickquip.llm.store_parts._base import _utc_now as _utc_now  # noqa: F401
from quickquip.llm.store_parts.agent_records import AgentRecordsStoreMixin
from quickquip.llm.store_parts.conversation import ConversationStoreMixin
from quickquip.llm.store_parts.group_settings import GroupSettingsMixin
from quickquip.llm.store_parts.memory import MemoryStoreMixin
from quickquip.llm.store_parts.session_archive import SessionArchiveMixin


class LLMStore(
    _StoreBase,
    ConversationStoreMixin,
    MemoryStoreMixin,
    SessionArchiveMixin,
    GroupSettingsMixin,
    AgentRecordsStoreMixin,
):
    """组合各域 mixin的 LLM 存储。

    MRO 顺序：``_StoreBase`` 必须第一位（提供 __init__ / _connect / _ensure_schema /
    _unavailable / _safe_load_tags），各域 mixin 互相独立，顺序不影响。
    """
