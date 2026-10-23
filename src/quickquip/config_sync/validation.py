"""Validate file assets through their domain parsers without changing active configuration."""

from pathlib import Path
import tomllib
from dataclasses import fields, is_dataclass
import math
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

import yaml

from quickquip.llm.config_errors import ConfigError


def _typed(value, annotation):
    if annotation is Any:
        return
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        for alternative in arguments:
            try:
                _typed(value, alternative)
                return
            except ValueError:
                pass
        raise ValueError("Invalid optional field type")
    if origin in (list, dict, tuple):
        if not isinstance(value, origin):
            raise ValueError("Invalid configuration container")
        if origin is dict:
            for key, item in value.items():
                _typed(key, arguments[0])
                _typed(item, arguments[1])
        else:
            for item in value:
                _typed(item, arguments[0])
        return
    if annotation is float:
        if type(value) not in (float, int) or not math.isfinite(value):
            raise ValueError("Invalid configuration number")
    elif annotation in (int, bool, str, type(None)):
        if type(value) is not annotation:
            raise ValueError("Invalid configuration scalar")
    elif not isinstance(value, annotation):
        raise ValueError("Invalid configuration value")
    if is_dataclass(value):
        hints = get_type_hints(type(value))
        for field in fields(value):
            _typed(getattr(value, field.name), hints[field.name])


def validate_asset_tree(root: Path):
    from quickquip.generation.config import load_generation_config
    from quickquip.games.config import load_games_config
    from quickquip.chat.awakening.config import load_awakening_config
    from quickquip.games.niuniu.text import load_niuniu_text
    from quickquip.common.admins import AdminRegistry
    from quickquip.common.sensitive_filter import SensitiveFilter
    from quickquip.llm.vocab import VocabIndex
    from quickquip.llm.identity import IdentityIndex
    from quickquip.chat.config import parse_chat_rule_state

    def rules(path):
        state = parse_chat_rule_state(tomllib.loads(path.read_text(encoding="utf-8")))
        for name, limits in state[0].items():
            for field in ("global_limit", "user_limit"):
                if type(limits.get(field)) is not int or limits[field] < 0:
                    raise ValueError(f"Invalid {name} quota")
        return None

    parsers = {
        "generation.toml": load_generation_config,
        "games.toml": load_games_config,
        "awakening.toml": load_awakening_config,
        "niuniu_text.toml": load_niuniu_text,
        "niuniu_text_safe.toml": load_niuniu_text,
        "admins.toml": lambda path: AdminRegistry(path)._parse(),
        "sensitive_words.toml": SensitiveFilter.from_toml,
        "chat_rules.toml": rules,
    }
    for filename, parse in parsers.items():
        path = root / "config" / filename
        if not path.exists():
            continue
        try:
            result = parse(path)
            if getattr(result, "load_error", None):
                raise ValueError("Domain configuration could not be loaded")
            if is_dataclass(result):
                _typed(result, type(result))
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ConfigError(
                "invalid_asset", "Invalid domain configuration", f"config/{filename}"
            ) from exc
    for path in (root / "llm_about").rglob("*.yaml"):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if raw is None:
                continue
            if path.name == "vocab.yaml":
                if not set(raw).intersection(
                    {"核心成员", "次核心成员", "次核心成员追加", "部分黑话解析"}
                ):
                    raise ValueError("Unknown vocabulary sections")
                VocabIndex.from_file(path)
            else:
                if not set(raw).intersection({"people", "special_accounts"}):
                    raise ValueError("Unknown identity sections")
                IdentityIndex.from_file(path)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ConfigError(
                "invalid_asset",
                "Invalid identity or vocabulary configuration",
                path.relative_to(root).as_posix(),
            ) from exc


def protect_draft_assets(document, before, target):
    """Asset changes must not introduce a new failure in a retained unpublished draft."""
    from quickquip.config_sync.bundle import validate_bundle

    previous_error = None
    try:
        validate_bundle({**before, "document": document})
    except ConfigError as exc:
        previous_error = (exc.code, exc.field_path)
    try:
        validate_bundle({**target, "document": document})
    except ConfigError as exc:
        if (exc.code, exc.field_path) != previous_error:
            raise ConfigError(
                "draft_conflict", "Asset changes break the retained draft", exc.field_path
            ) from exc
