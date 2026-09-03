from __future__ import annotations

# ── scope / history limits ──────────────────────────────────────────
MAX_TRIGGER_CONTEXT_MESSAGES = 20
MAX_MEMORY_RETRIEVAL_ITEMS = 8
MAX_STORED_MEMORY_ITEMS = 200
DEFAULT_PRIVATE_HISTORY_LIMIT = 256
MAX_GROUP_STORED_CONVERSATION_MESSAGES = 20
MAX_PRIVATE_STORED_CONVERSATION_MESSAGES = 256

# ── builtin tool names & discovery defaults ─────────────────────────
# Single source of truth for tool-name constants shared between
# ``service.py`` (tool-discovery policy + tool-loop invocation) and
# ``service_parts/tools.py`` (builtin tool registration). Previously
# these were duplicated byte-for-byte in both modules.
SEARCH_TOOL_NAME = "search_web"
TOOL_SEARCH_NAME = "tool_search"
TOOL_LIST_NAME = "tool_list"
SEARCH_TOOL_FAILSAFE_MAX_ROUNDS = 64
SEARCH_TOOL_FAILSAFE_MAX_CALLS_PER_ROUND = 64
PRIVATE_UNAVAILABLE_TOOLS = {"get_group_stats", "get_rule_status", "manage_scheduled_messages"}
DEFAULT_ALWAYS_LOADED_TOOLS = [
    TOOL_SEARCH_NAME,
    TOOL_LIST_NAME,
    "get_identity",
    "list_memories",
    SEARCH_TOOL_NAME,
]
DEFAULT_ENABLED_TOOLS = [
    TOOL_SEARCH_NAME,
    TOOL_LIST_NAME,
    "get_identity",
    "list_memories",
    SEARCH_TOOL_NAME,
    "get_group_stats",
    "get_rule_status",
    "search_recent_messages",
    "get_llm_status",
    "get_current_model",
    "get_health_status",
]
