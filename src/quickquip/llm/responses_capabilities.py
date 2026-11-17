"""Declarative Responses hosted capabilities, shared by policy and wire profiles."""
from types import MappingProxyType

RESPONSES_HOSTED_TOOLS = MappingProxyType({
    "codex-relay-standalone-search": frozenset({"image_generation"}),
    "openai-public": frozenset(),
    "codex-http-relay": frozenset(),
    "codex-relay-hosted-tools": frozenset({"image_generation", "web_search"}),
})

RESPONSES_STANDALONE_SEARCH = frozenset({"codex-relay-standalone-search"})
