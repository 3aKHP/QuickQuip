"""Provider client factory.

Dispatches to the concrete provider client based on ``ProviderConfig.protocol``.
Kept separate so ``__init__.py`` can re-export it without importing the
concrete subclasses at module top-level of the factory module.
"""
from __future__ import annotations

from quickquip.llm.config import ProviderConfig
from quickquip.llm.provider.base import BaseProviderClient, LLMProviderError
from quickquip.llm.provider.claude import ClaudeProviderClient
from quickquip.llm.provider.gemini import GeminiProviderClient
from quickquip.llm.provider.openai import OpenAIProviderClient
from quickquip.llm.provider.retry import RetryPolicy


def build_provider_client(config: ProviderConfig, *, retry_policy: RetryPolicy | None = None) -> BaseProviderClient:
    if config.protocol == "openai":
        return OpenAIProviderClient(config, retry_policy=retry_policy)
    if config.protocol == "claude":
        return ClaudeProviderClient(config, retry_policy=retry_policy)
    if config.protocol == "gemini":
        return GeminiProviderClient(config, retry_policy=retry_policy)
    raise LLMProviderError(f"未知 provider 协议：{config.protocol}")
