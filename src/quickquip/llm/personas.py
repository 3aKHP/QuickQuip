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
}


def _read_personas(raw_personas: list[dict[str, Any]]) -> dict[str, PersonaConfig]:
    personas: dict[str, PersonaConfig] = {}
    for entry in raw_personas:
        entry = expand_env_value(entry)
        persona_id = str(entry.get("id", "")).strip()
        if not persona_id:
            continue
        raw_scope = entry.get("scope", [])
        if isinstance(raw_scope, str):
            raw_scope = [raw_scope]
        parsed_scope = [
            s for s in (str(s).strip().lower() for s in raw_scope) if s in {"group", "private"}
        ]
        extras = {k: v for k, v in entry.items() if k not in _KNOWN_PERSONA_KEYS}
        personas[persona_id] = PersonaConfig(
            id=persona_id,
            display_name=str(entry.get("display_name", persona_id)).strip() or persona_id,
            system_prompt=str(entry.get("system_prompt", "")).strip(),
            style_prompt=str(entry.get("style_prompt", "")).strip(),
            scope=parsed_scope,
            extras=extras,
        )
    return personas


def _load_personas_from_dir(personas_dir: Path) -> list[dict[str, Any]]:
    """Load personas from a directory of TOML files.

    Each file may define a persona using flat top-level keys (id, display_name,
    system_prompt, style_prompt, plus any extras), or via a [[personas]] array
    for compatibility.

    A special file ``_shared.toml`` may define:
    - ``shared_system_prompt``: appended to every persona's system_prompt
    - ``shared_style_prompt``: appended to every persona's style_prompt

    Files are loaded in lexicographic order. ``_shared.toml`` is processed
    first and never treated as a persona definition itself.
    """
    if not personas_dir.is_dir():
        return []

    # Load shared rules first
    shared_system = ""
    shared_style = ""
    shared_path = personas_dir / "_shared.toml"
    if shared_path.exists():
        try:
            with shared_path.open("rb") as fh:
                shared_data = tomllib.load(fh)
            shared_system = str(shared_data.get("shared_system_prompt", "")).strip()
            shared_style = str(shared_data.get("shared_style_prompt", "")).strip()
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
            entry = dict(data)
            # Inject shared content
            if shared_system and entry.get("inherit_shared", True):
                existing = str(entry.get("system_prompt", "")).rstrip()
                entry["system_prompt"] = (
                    (existing + "\n\n" + shared_system).lstrip() if existing else shared_system
                )
            if shared_style and entry.get("inherit_shared", True):
                existing = str(entry.get("style_prompt", "")).rstrip()
                entry["style_prompt"] = (
                    (existing + "\n\n" + shared_style).lstrip() if existing else shared_style
                )
            personas.append(entry)
        elif "personas" in data:
            for entry in data["personas"]:
                entry = dict(entry)
                if shared_system and entry.get("inherit_shared", True):
                    existing = str(entry.get("system_prompt", "")).rstrip()
                    entry["system_prompt"] = (
                        (existing + "\n\n" + shared_system).lstrip() if existing else shared_system
                    )
                if shared_style and entry.get("inherit_shared", True):
                    existing = str(entry.get("style_prompt", "")).rstrip()
                    entry["style_prompt"] = (
                        (existing + "\n\n" + shared_style).lstrip() if existing else shared_style
                    )
                personas.append(entry)

    return personas


def load_personas(personas_dir: Path) -> dict[str, PersonaConfig]:
    return _read_personas(_load_personas_from_dir(personas_dir))
