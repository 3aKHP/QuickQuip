"""Independent persona files and shared prompt inheritance."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any
from quickquip.common.config_utils import expand_env_value
from quickquip.llm.config import PersonaConfig

logger = logging.getLogger(__name__)
_KNOWN_PERSONA_KEYS = {
    "id",
    "display_name",
    "system_prompt",
    "style_prompt",
    "scope",
    "inherit_shared",
    "shared_host_rules",
    "shared_style_rules",
}

_SHARED_KEYS = (
    "shared_system_prompt",
    "shared_style_prompt",
    "shared_group_system_prompt",
    "shared_private_system_prompt",
    "shared_group_style_prompt",
    "shared_private_style_prompt",
)


def _normalize_scope(raw_scope: Any) -> list[str]:
    if isinstance(raw_scope, str):
        raw_scope = [raw_scope]
    if not isinstance(raw_scope, list):
        return []
    return [
        s for s in (str(item).strip().lower() for item in raw_scope) if s in {"group", "private"}
    ]


def _resolve_shared_rules(shared_data: dict[str, str], raw_scope: Any) -> tuple[str, str]:
    scope_set = set(_normalize_scope(raw_scope))
    if scope_set == {"private"}:
        sys_rule = (
            shared_data["shared_private_system_prompt"] or shared_data["shared_system_prompt"]
        )
        sty_rule = (
            shared_data["shared_private_style_prompt"] or shared_data["shared_style_prompt"]
        )
        return sys_rule, sty_rule
    if scope_set == {"group"}:
        sys_rule = shared_data["shared_group_system_prompt"] or shared_data["shared_system_prompt"]
        sty_rule = shared_data["shared_group_style_prompt"] or shared_data["shared_style_prompt"]
        return sys_rule, sty_rule
    return shared_data["shared_system_prompt"], shared_data["shared_style_prompt"]


def _strip_leading_divider(text: str) -> str:
    lines = text.splitlines()
    while lines and lines[0].strip() in ("", "---"):
        lines.pop(0)
    return "\n".join(lines).strip()


def _schema_version_of(entry: dict[str, Any]) -> int:
    raw = entry.get("schema_version", 1)
    if isinstance(raw, bool):
        return 1
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def _apply_shared_to_entry(entry: dict[str, Any], shared_data: dict[str, str]) -> dict[str, Any]:
    if not entry.get("inherit_shared", True):
        return entry
    shared_system, shared_style = _resolve_shared_rules(shared_data, entry.get("scope", []))
    if _schema_version_of(entry) >= 3:
        if shared_system:
            entry["shared_host_rules"] = _strip_leading_divider(shared_system)
        if shared_style:
            entry["shared_style_rules"] = shared_style
        return entry
    if shared_system:
        existing = str(entry.get("system_prompt", "")).rstrip()
        entry["system_prompt"] = (
            (existing + "\n\n" + shared_system).lstrip() if existing else shared_system
        )
    if shared_style:
        existing = str(entry.get("style_prompt", "")).rstrip()
        entry["style_prompt"] = (
            (existing + "\n\n" + shared_style).lstrip() if existing else shared_style
        )
    return entry


def _read_personas(raw_personas: list[dict[str, Any]]) -> dict[str, PersonaConfig]:
    personas: dict[str, PersonaConfig] = {}
    for entry in raw_personas:
        entry = expand_env_value(entry)
        persona_id = str(entry.get("id", "")).strip()
        if not persona_id:
            continue
        parsed_scope = _normalize_scope(entry.get("scope", []))
        extras = {k: v for k, v in entry.items() if k not in _KNOWN_PERSONA_KEYS}
        personas[persona_id] = PersonaConfig(
            id=persona_id,
            display_name=str(entry.get("display_name", persona_id)).strip() or persona_id,
            system_prompt=str(entry.get("system_prompt", "")).strip(),
            style_prompt=str(entry.get("style_prompt", "")).strip(),
            scope=parsed_scope,
            extras=extras,
            shared_host_rules=str(entry.get("shared_host_rules", "")).strip(),
            shared_style_rules=str(entry.get("shared_style_rules", "")).strip(),
        )
    return personas


def _load_personas_from_dir(personas_dir: Path) -> list[dict[str, Any]]:
    """Load personas from a directory of TOML files.

    Each file may define a persona using flat top-level keys (id, display_name,
    system_prompt, style_prompt, plus any extras), or via a [[personas]] array
    for compatibility.

    A special file ``_shared.toml`` may define:
    - ``shared_system_prompt`` / ``shared_style_prompt``: defaults for all personas
    - ``shared_group_system_prompt`` / ``shared_group_style_prompt``: optional overrides when
      ``scope = ["group"]``
    - ``shared_private_system_prompt`` / ``shared_private_style_prompt``: optional overrides when
      ``scope = ["private"]``

    For ``schema_version >= 3``, shared rules populate ``shared_host_rules`` and
    ``shared_style_rules`` so ``build_system_prompt`` can place them into the
    host contract and voice anchor sections without mutating ``system_prompt``.

    Files are loaded in lexicographic order. ``_shared.toml`` is processed
    first and never treated as a persona definition itself.
    """
    if not personas_dir.is_dir():
        return []

    # Load shared rules first
    shared_data = {key: "" for key in _SHARED_KEYS}
    shared_path = personas_dir / "_shared.toml"
    if shared_path.exists():
        try:
            with shared_path.open("rb") as fh:
                raw_shared = tomllib.load(fh)
            for key in _SHARED_KEYS:
                shared_data[key] = str(raw_shared.get(key, "")).strip()
        except tomllib.TOMLDecodeError as exc:
            logger.warning("跳过损坏的 _shared.toml：%s", exc)

    personas: list[dict[str, Any]] = []
    for toml_file in sorted(personas_dir.glob("*.toml")):
        if toml_file.name.startswith("_"):
            continue  # skip _shared.toml and other reserved files
        try:
            with toml_file.open("rb") as fh:
                data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            logger.warning("跳过损坏的人格文件 %s：%s", toml_file.name, exc)
            continue

        # Support flat top-level keys (preferred) or [[personas]] array
        if "id" in data:
            personas.append(_apply_shared_to_entry(dict(data), shared_data))
        elif "personas" in data:
            for entry in data["personas"]:
                personas.append(_apply_shared_to_entry(dict(entry), shared_data))

    return personas


def load_personas(personas_dir: Path) -> dict[str, PersonaConfig]:
    return _read_personas(_load_personas_from_dir(personas_dir))
