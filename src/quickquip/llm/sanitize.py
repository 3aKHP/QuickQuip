"""Error-message masking policy shared by provider, MCP, and usage persistence.

错误消息在落库/展示前遮蔽 URL 并截断：httpx ``RequestError`` 字符串包含
完整请求 URL，query 中可能携带凭据。本模块为纯函数叶子，无 llm 内部依赖。
"""
from __future__ import annotations

import re

MAX_SAFE_ERROR_LENGTH = 200
_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+")


def mask_urls(text: str) -> str:
    """Replace http(s) URLs with ``[url]``."""
    return _URL_PATTERN.sub("[url]", text)


def sanitize_error_message(message: str, *, limit: int = MAX_SAFE_ERROR_LENGTH) -> str:
    """Mask URLs in an error message and truncate it for safe persistence/display."""
    return mask_urls(message)[:limit]
