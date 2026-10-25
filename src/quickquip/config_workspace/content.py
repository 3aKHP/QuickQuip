"""Read configuration-only snapshots and validate a complete proposed configuration."""

from copy import deepcopy
from dataclasses import asdict
import json
import os
import sqlite3
from io import StringIO
from pathlib import Path
import tempfile

from dotenv import dotenv_values

from quickquip.common.config_utils import expansion_environment
from quickquip.configuration.errors import ConfigError
from quickquip.configuration.paths import StoragePaths
from quickquip.configuration.validation import validate_asset_tree
from quickquip.config_workspace.inventory import body, read_files, safe_path, GROUP_FILES
from quickquip.config_workspace import text
from quickquip.config_workspace.database import read_only
from quickquip.llm.config_document import validate_document
from quickquip.llm.config_service import ConfigService
from quickquip.llm.scope_types import GroupSettingsOverride
from quickquip.llm.config import REASONING_EFFORT_CHOICES
from quickquip.llm.config_store import projection_consistent


def read(root):
    root = Path(root)
    path = StoragePaths(root).configuration
    if not path.exists():
        raise ConfigError("not_initialized", "Initialize or migrate configuration storage first")
    with read_only(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        meta = connection.execute("SELECT * FROM config_meta").fetchone()
        if meta["schema_version"] != 4:
            raise ConfigError("migration_required", "Migrate configuration storage before qqconf")
        projection_consistent(connection)
        scopes = {
            row["group_id"]: {
                key: value
                for key, value in dict(row).items()
                if key not in ("group_id", "updated_at") and value is not None
            }
            for row in connection.execute("SELECT * FROM scope_settings")
        }
        for scope in scopes.values():
            for key in (
                "enabled",
                "memory_enabled",
                "auto_memory_enabled",
                "allow_prefix",
                "allow_at",
                "agent_delivery_intermediate_enabled",
                "agent_delivery_final_enabled",
            ):
                if key in scope:
                    scope[key] = bool(scope[key])
        modes = dict(connection.execute("SELECT group_id,text_mode FROM niuniu_group_text"))
        document = json.loads(meta["document"])
    return {"document": document, "scopes": scopes, "text_modes": modes, "files": read_files(root)}


def validate(snapshot):
    environment = dict(os.environ)
    dotenv = snapshot["files"].get(".env")
    if dotenv is not None:
        raw = body(dotenv)
        text.parse(".env", raw)
        environment.update(
            {
                key: value
                for key, value in dotenv_values(stream=StringIO(raw.decode("utf-8"))).items()
                if value is not None
            }
        )
    with expansion_environment(environment):
        return _validate(snapshot)


def _validate(snapshot):
    value = deepcopy(snapshot)
    # Materialize candidate assets; environment expansion stays inside validation.
    with tempfile.TemporaryDirectory(prefix="qqconf-validation-") as directory:
        root = Path(directory)
        for name, item in value["files"].items():
            parsed = text.parse(name, body(item))
            target = safe_path(root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body(item))
            if name in GROUP_FILES:
                if not isinstance(parsed, dict):
                    raise ConfigError("invalid_configuration", "Expected group configuration", name)
                if name == "data/rule_switch.json":
                    if any(
                        not group.isdigit()
                        or not isinstance(rules, list)
                        or any(not isinstance(rule, str) for rule in rules)
                        for group, rules in parsed.items()
                    ):
                        raise ConfigError(
                            "invalid_configuration", "Expected rule names by numeric group", name
                        )
                else:
                    groups = parsed.get("enabled")
                    if not isinstance(groups, list) or any(
                        not str(group).isdigit() for group in groups
                    ):
                        raise ConfigError(
                            "invalid_configuration", "Expected numeric enabled groups", name
                        )
            if name.endswith("scheduled_messages.json"):
                from quickquip.chat.scheduled_messages import ScheduledMessage

                if not isinstance(parsed, dict) or not isinstance(parsed.get("jobs"), list):
                    raise ConfigError("invalid_configuration", "Expected recurring jobs", name)
                try:
                    jobs = [ScheduledMessage.from_dict(job) for job in parsed["jobs"]]
                except (ValueError, TypeError, KeyError, AttributeError):
                    raise ConfigError(
                        "invalid_configuration", "Invalid recurring job", name
                    ) from None
                if any(not job.recurring for job in jobs) or len({j.id for j in jobs}) != len(jobs):
                    raise ConfigError(
                        "invalid_configuration", "Expected unique recurring jobs", name
                    )
        validate_asset_tree(root)
        value["document"] = validate_document(value["document"], config_dir=root / "config")
        personas = root / "config/personas"
        from quickquip.llm.personas import load_personas

        catalog = load_personas(personas)
        default = value["document"]["settings"]["runtime"]["default_persona"]
        if default and default not in catalog:
            raise ConfigError("dependency_conflict", "Default persona is missing", "personas")
        defaults = asdict(GroupSettingsOverride())
        booleans = {
            "enabled",
            "memory_enabled",
            "auto_memory_enabled",
            "allow_prefix",
            "allow_at",
            "agent_delivery_intermediate_enabled",
            "agent_delivery_final_enabled",
        }
        for scope, settings in value["scopes"].items():
            ident = scope.removeprefix("private:")
            if not ident.isdigit() or any(key not in defaults for key in settings):
                raise ConfigError("invalid_configuration", "Invalid scope settings", scope)
            if scope.startswith("private:") and "enabled" in settings:
                raise ConfigError("invalid_field", "Private activity is runtime state", scope)
            for key, item in settings.items():
                if item is None:
                    continue
                if key in booleans and type(item) is not bool:
                    raise ConfigError("invalid_field", "Expected boolean", f"{scope}.{key}")
                if key == "history_limit" and (type(item) is not int or item < 0):
                    raise ConfigError("invalid_field", "Expected nonnegative integer", scope)
                if key not in booleans | {"history_limit"} and not isinstance(item, str):
                    raise ConfigError("invalid_field", "Expected string", f"{scope}.{key}")
            if settings.get("reasoning_effort") not in (None, *REASONING_EFFORT_CHOICES):
                raise ConfigError("invalid_field", "Invalid reasoning effort", scope)
            ConfigService.validate_group_reference(
                value["document"],
                settings.get("provider_id"),
                settings.get("model"),
                f"scopes.{scope}",
            )
            if settings.get("persona_id") not in (None, "", *catalog):
                raise ConfigError("dependency_conflict", "Scope persona is missing", scope)
        value["scopes"] = {
            scope: {key: item for key, item in settings.items() if item is not None}
            for scope, settings in value["scopes"].items()
        }
        for group, mode in value["text_modes"].items():
            if not group.isdigit() or mode not in ("default", "safe"):
                raise ConfigError("invalid_field", "Invalid game text mode", group)
    return value
