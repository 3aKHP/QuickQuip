"""LLM provider client package.

Split from the former monolithic ``provider.py`` into:
- :mod:`.trace` — request/response tracing infrastructure
- :mod:`.base` — ``BaseProviderClient``, data classes, shared utilities
- :mod:`.openai` / :mod:`.claude` / :mod:`.gemini` — concrete clients
- :mod:`.factory` — ``build_provider_client`` dispatcher

This ``__init__`` re-exports the full public surface (plus a few private
symbols that external modules already depend on) so that
``from quickquip.llm.provider import X`` continues to work unchanged.
"""
from __future__ import annotations

# Public data classes & exception
from quickquip.llm.provider.base import (
    BaseProviderClient,
    LLMImageInput,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMWebSearchReport,
    LLMWebSearchSource,
)

# Public utilities
from quickquip.llm.provider.base import (
    sanitize_gemini_schema,
    strip_leading_reasoning_content,
)

# Public trace entry points
from quickquip.llm.provider.trace import (
    collect_trace_calls,
    trace_store,
)

# Factory
from quickquip.llm.provider.factory import build_provider_client

# Concrete clients (re-exported for tests and plugins/llm_provider.py)
from quickquip.llm.provider.openai import OpenAIProviderClient
from quickquip.llm.provider.claude import ClaudeProviderClient
from quickquip.llm.provider.claude import _detect_stainless_os as _detect_stainless_os  # noqa: F401
from quickquip.llm.provider.gemini import GeminiProviderClient

# Private symbols re-exported because external code depends on them:
#   _is_retryable       — quickquip.llm.tool_loop
#   _TRACE_FLAG_FILE    — quickquip.app.web.routes.diagnostics
# These use the `name as name` explicit re-export form so ruff treats them
# as intentional re-exports rather than unused imports (F401).
from quickquip.llm.provider.base import _is_retryable as _is_retryable  # noqa: F401
from quickquip.llm.provider.trace import _TRACE_FLAG_FILE as _TRACE_FLAG_FILE  # noqa: F401

__all__ = [
    "BaseProviderClient",
    "OpenAIProviderClient",
    "ClaudeProviderClient",
    "GeminiProviderClient",
    "LLMImageInput",
    "LLMProviderError",
    "LLMRequest",
    "LLMResponse",
    "LLMWebSearchReport",
    "LLMWebSearchSource",
    "build_provider_client",
    "sanitize_gemini_schema",
    "strip_leading_reasoning_content",
    "collect_trace_calls",
    "trace_store",
]
