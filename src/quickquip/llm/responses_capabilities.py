"""Declarative Responses hosted capabilities, shared by policy and wire profiles."""
from types import MappingProxyType

RESPONSES_HOSTED_TOOLS = MappingProxyType({
    "openai-public": frozenset(),
    "codex-http-relay": frozenset(),
    "codex-relay-hosted-tools": frozenset({"image_generation", "web_search"}),
})
