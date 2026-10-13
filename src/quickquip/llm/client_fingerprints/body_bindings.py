"""Validate and project Profile-owned dynamic JSON fields."""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from quickquip.llm.client_fingerprints.session_projection import SESSION_BINDINGS
from quickquip.llm.config_errors import ConfigError

BodyBindings = tuple[tuple[str, str], ...]
# Protocol data vocabulary; credential classification does not depend on Profile selection.
CACHE_AFFINITY_FIELD = "prompt_cache_key"

if TYPE_CHECKING:
    from quickquip.llm.provider.base import LLMRequest


def parse_body_bindings(raw: Any, protocol: str, location: str) -> BodyBindings:
    if (protocol != "openai_responses" or not isinstance(raw, dict)
            or set(raw) - {CACHE_AFFINITY_FIELD}
            or any(source != "business_session_id" for source in raw.values())):
        raise ConfigError("invalid_profile", "Unsupported Body binding", location)
    return tuple(raw.items())


def validate_body_binding_overrides(
    bindings: BodyBindings, overrides: dict[str, Any], location: str = "extra_body",
) -> None:
    for field, _ in bindings:
        if field in overrides:
            raise ConfigError(
                "profile_owned_body", "Dynamic Body fields are managed by the selected Profile",
                f"{location}.{field}",
            )


def project_body_bindings(
    bindings: BodyBindings, request: LLMRequest, payload: dict[str, Any], *, data_dir: Path,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    validate_body_binding_overrides(bindings, overrides)
    values = {source: SESSION_BINDINGS[source](request, data_dir)
              for source in {source for _, source in bindings}}
    return {**payload, **{field: values[source] for field, source in bindings}}
