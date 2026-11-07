from __future__ import annotations

from quickquip.llm.skills import (
    ACTIVATE_SKILL_TOOL_NAME,
    READ_SKILL_RESOURCE_TOOL_NAME,
    RUN_SKILL_SCRIPT_TOOL_NAME,
    SEARCH_SKILL_RESOURCES_TOOL_NAME,
)

# ── scope / history limits ──────────────────────────────────────────
MAX_TRIGGER_CONTEXT_MESSAGES = 20
MAX_MEMORY_RETRIEVAL_ITEMS = 8
MAX_STORED_MEMORY_ITEMS = 1000
# 会话消息统一存储硬上限（群聊/私聊同值）：纪元裁剪以锚点为主键，此值仅为
# 锚点全部缺失（进程重启后）或单 scope 行数失控时的兜底。64k token 纪元
# ≈1.3k 行，2048 留约 1.5× 余量。
MAX_STORED_CONVERSATION_MESSAGES = 2048

# ── builtin tool names & discovery defaults ─────────────────────────
# Single source of truth for tool-name constants shared between
# ``service.py`` (tool-discovery policy + tool-loop invocation) and
# ``service_parts/tools.py`` (builtin tool registration). Previously
# these were duplicated byte-for-byte in both modules.
# Skill 工具名定义在 llm/skills/tools/ 各工具模块，此处统一 re-export。
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
    "read_memory",
    "write_memory",
    "delete_memory",
    SEARCH_TOOL_NAME,
    ACTIVATE_SKILL_TOOL_NAME,
]
# get_group_stats / get_rule_status / get_health_status 已移出默认面（生产 0 调用），
# 仍注册并经 config.tools.enabled opt-in；前两者在 PRIVATE_UNAVAILABLE_TOOLS 中，
# 私聊面同样经 opt-in 后才会被过滤。
# 群历史双工具（#72）登记进默认面（延迟池候选），但只在「全局配置 + 群开关」
# 双开的面曝光（_get_enabled_tool_names 的 history_enabled 过滤）。
DEFAULT_ENABLED_TOOLS = [
    TOOL_SEARCH_NAME,
    TOOL_LIST_NAME,
    "get_identity",
    "list_memories",
    "read_memory",
    "write_memory",
    "delete_memory",
    SEARCH_TOOL_NAME,
    "search_recent_messages",
    "search_group_history",
    "read_group_history",
    "get_llm_status",
    ACTIVATE_SKILL_TOOL_NAME,
    READ_SKILL_RESOURCE_TOOL_NAME,
    SEARCH_SKILL_RESOURCES_TOOL_NAME,
    RUN_SKILL_SCRIPT_TOOL_NAME,
]

# ── scope gate queue policy（设计 §5.2「过期被动触发按现有策略取消」）────
# 被动类触发（群被动唤醒 / 无聊唤醒）在闸门后的排队预算：超时即取消
# 本轮（空回复、不调 LLM、不发送）。聊天节奏下普通轮次持有 2–15s，
# 预算给足四倍余量；只有排到长生成（原生生图 4–7 分钟）后才会触发
# 取消——彼时再插话已是过期噪音。主动 @/前缀、私聊与定时触发不受
# 限制：用户明确要答案或计划任务按点发话，晚到也要发。
PASSIVE_TRIGGER_QUEUE_PATIENCE_S = 60.0
