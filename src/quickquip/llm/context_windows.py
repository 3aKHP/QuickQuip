"""模型上下文窗口解析：provider 显式配置 > 内置策展表 > capacity unknown。

内置表按模型家族前缀保守策展（存疑条目取低值：低估收紧预算属安全侧，
高估可能放行超限 payload）。中继自定义模型名、表外模型一律 unknown，
由维护者显式配置 ``model_context_windows`` 补齐；显式键永远优先。
"""
from __future__ import annotations

from collections.abc import Mapping

# 前缀规则（小写匹配，长前缀优先）。
_BUILTIN_PREFIX_RULES: tuple[tuple[str, int], ...] = (
    ("claude-", 200_000),
    ("gemini-3", 1_000_000),
    ("gemini-2.5", 1_000_000),
    ("gemini-2.0", 1_000_000),
    ("gemini-1.5-pro", 2_000_000),
    ("gemini-1.5", 1_000_000),
    ("gpt-5", 400_000),
    ("gpt-4.1", 1_000_000),
    ("gpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("o3", 200_000),
    ("o4", 200_000),
    ("deepseek", 128_000),
    ("qwen3", 262_144),
    ("qwen2.5", 131_072),
    ("kimi", 256_000),
    ("glm-4.5", 200_000),
    ("glm-4", 128_000),
    ("grok-4", 256_000),
    ("grok-3", 131_072),
    ("minimax-m2", 204_800),
    ("mistral-large", 128_000),
)

_PREFIX_ORDER = sorted(_BUILTIN_PREFIX_RULES, key=lambda rule: -len(rule[0]))


def lookup_builtin_context_window(model: str) -> int | None:
    """按家族前缀查内置窗口；无匹配返回 None（capacity unknown）。"""
    name = model.strip().lower()
    if not name:
        return None
    for prefix, window in _PREFIX_ORDER:
        if name.startswith(prefix):
            return window
    return None


def resolve_context_window(
    explicit_windows: Mapping[str, int], model: str
) -> int | None:
    """窗口解析的单一入口：显式配置精确匹配 > 内置前缀 > None。"""
    explicit = explicit_windows.get(model)
    if explicit is not None and int(explicit) > 0:
        return int(explicit)
    return lookup_builtin_context_window(model)
