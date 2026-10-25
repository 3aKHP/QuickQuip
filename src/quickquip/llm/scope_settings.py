"""LLM scope configuration repository in the shared configuration database."""

from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone

from quickquip.configuration.database import connect
from quickquip.configuration.errors import ConfigError
from quickquip.configuration.paths import PATHS, data_directory
from quickquip.common.config_writes import configuration_write
from quickquip.llm.scope_types import GroupSettingsOverride


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


class ScopeSettingsRepository:
    """Only persistent preferences; private-session activity belongs to LLMStore."""

    def __init__(self, path=PATHS.configuration, *, data_dir=None):
        self.path = Path(path)
        self.data_dir = Path(data_dir) if data_dir else data_directory(self.path)

    @contextmanager
    def _connect(self, *, write=False):
        if write:
            with configuration_write(self.data_dir), connect(self.path, write=True) as connection:
                yield connection
        else:
            with connect(self.path) as connection:
                yield connection

    def list(self):
        with self._connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM scope_settings ORDER BY updated_at DESC"
                )
            ]

    def delete(self, scope):
        with self._connect(write=True) as connection:
            return connection.execute(
                "DELETE FROM scope_settings WHERE group_id=?", (str(scope),)
            ).rowcount

    def get_group_settings(self, group_id: int | str) -> GroupSettingsOverride:
        with self._connect() as conn:
            row = conn.execute(
                "\n"
                "                SELECT enabled, memory_enabled, auto_memory_enabled, "
                "agent_delivery_intermediate_enabled, agent_delivery_final_enabled, provider_id, "
                "model, persona_id, trigger_prefix, allow_prefix, allow_at, history_limit, "
                "reasoning_effort\n"
                "                FROM scope_settings\n"
                "                WHERE group_id = ?\n"
                "                ",
                (str(group_id),),
            ).fetchone()
        if row is None:
            return GroupSettingsOverride()
        return GroupSettingsOverride(
            enabled=None if row["enabled"] is None else bool(row["enabled"]),
            memory_enabled=None if row["memory_enabled"] is None else bool(row["memory_enabled"]),
            auto_memory_enabled=(
                None if row["auto_memory_enabled"] is None else bool(row["auto_memory_enabled"])
            ),
            agent_delivery_intermediate_enabled=(
                None
                if row["agent_delivery_intermediate_enabled"] is None
                else bool(row["agent_delivery_intermediate_enabled"])
            ),
            agent_delivery_final_enabled=(
                None
                if row["agent_delivery_final_enabled"] is None
                else bool(row["agent_delivery_final_enabled"])
            ),
            provider_id=row["provider_id"],
            model=row["model"],
            persona_id=row["persona_id"],
            trigger_prefix=row["trigger_prefix"],
            allow_prefix=None if row["allow_prefix"] is None else bool(row["allow_prefix"]),
            allow_at=None if row["allow_at"] is None else bool(row["allow_at"]),
            history_limit=None if row["history_limit"] is None else int(row["history_limit"]),
            reasoning_effort=row["reasoning_effort"] or None,
        )

    def update_group_settings(self, group_id: int | str, **fields: object) -> None:
        group_key = str(group_id)
        allowed_fields = {
            "enabled",
            "memory_enabled",
            "auto_memory_enabled",
            "agent_delivery_intermediate_enabled",
            "agent_delivery_final_enabled",
            "provider_id",
            "model",
            "persona_id",
            "trigger_prefix",
            "allow_prefix",
            "allow_at",
            "history_limit",
            "reasoning_effort",
        }
        if group_key.startswith("private:") and "enabled" in fields:
            raise ConfigError(
                "invalid_field", "Use private-session state to pause or resume a chat", "enabled"
            )
        payload = {key: value for key, value in fields.items() if key in allowed_fields}
        if not payload:
            return
        payload["updated_at"] = _utc_now()

        with self._connect(write=True) as conn:
            current = conn.execute(
                "SELECT group_id FROM scope_settings WHERE group_id = ?",
                (group_key,),
            ).fetchone()

            if current is None:
                columns = ["group_id", *payload.keys()]
                values = [group_key, *payload.values()]
                placeholders = ", ".join("?" for _ in columns)
                conn.execute(
                    f"INSERT INTO scope_settings ({', '.join(columns)}) VALUES ({placeholders})",
                    values,
                )
                return

            assignments = ", ".join(f"{key} = ?" for key in payload)
            conn.execute(
                f"UPDATE scope_settings SET {assignments} WHERE group_id = ?",
                [*payload.values(), group_key],
            )
