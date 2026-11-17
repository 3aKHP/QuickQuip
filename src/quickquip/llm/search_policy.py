"""Effective search routing for application requests; no provider imports."""
from typing import Literal

from quickquip.llm.config import ProviderConfig, provider_builtin_search_active

SearchMode = Literal[
    "none", "local", "gemini_grounding", "responses_hosted", "responses_standalone",
]


def resolve_search_mode(
    provider: ProviderConfig, *, tools_allowed: bool, local_search_enabled: bool,
) -> SearchMode:
    from quickquip.llm.responses_capabilities import RESPONSES_STANDALONE_SEARCH

    if (provider.protocol == "openai_responses"
            and provider.responses_profile in RESPONSES_STANDALONE_SEARCH):
        return "responses_standalone" if tools_allowed else "none"
    if provider_builtin_search_active(provider):
        if provider.protocol == "gemini":
            return "gemini_grounding"
        if tools_allowed:
            return "responses_hosted"
    return "local" if tools_allowed and local_search_enabled else "none"
