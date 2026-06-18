"""GroupSettingsMixin：群聊 LLM 设置覆盖的读写。"""

from __future__ import annotations

from quickquip.llm.store_parts._base import GroupSettingsOverride, _utc_now


class GroupSettingsMixin:
    """群聊设置域。依赖 _StoreBase 的 _connect / _unavailable。"""

    def get_group_settings(self, group_id: int | str) -> GroupSettingsOverride:
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT enabled, memory_enabled, auto_memory_enabled, provider_id, model, persona_id, trigger_prefix, allow_prefix, allow_at, history_limit
                FROM group_settings
                WHERE group_id = ?
                """,
                (str(group_id),),
            ).fetchone()
        if row is None:
            return GroupSettingsOverride()
        return GroupSettingsOverride(
            enabled=None if row["enabled"] is None else bool(row["enabled"]),
            memory_enabled=None if row["memory_enabled"] is None else bool(row["memory_enabled"]),
            auto_memory_enabled=None if row["auto_memory_enabled"] is None else bool(row["auto_memory_enabled"]),
            provider_id=row["provider_id"],
            model=row["model"],
            persona_id=row["persona_id"],
            trigger_prefix=row["trigger_prefix"],
            allow_prefix=None if row["allow_prefix"] is None else bool(row["allow_prefix"]),
            allow_at=None if row["allow_at"] is None else bool(row["allow_at"]),
            history_limit=None if row["history_limit"] is None else int(row["history_limit"]),
        )

    def update_group_settings(self, group_id: int | str, **fields: object) -> None:
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        group_key = str(group_id)
        allowed_fields = {
            "enabled",
            "memory_enabled",
            "auto_memory_enabled",
            "provider_id",
            "model",
            "persona_id",
            "trigger_prefix",
            "allow_prefix",
            "allow_at",
            "history_limit",
        }
        payload = {key: value for key, value in fields.items() if key in allowed_fields}
        if not payload:
            return
        payload["updated_at"] = _utc_now()

        with self._connect() as conn:
            current = conn.execute(
                "SELECT group_id FROM group_settings WHERE group_id = ?",
                (group_key,),
            ).fetchone()

            if current is None:
                columns = ["group_id", *payload.keys()]
                values = [group_key, *payload.values()]
                placeholders = ", ".join("?" for _ in columns)
                conn.execute(
                    f"INSERT INTO group_settings ({', '.join(columns)}) VALUES ({placeholders})",
                    values,
                )
                return

            assignments = ", ".join(f"{key} = ?" for key in payload)
            conn.execute(
                f"UPDATE group_settings SET {assignments} WHERE group_id = ?",
                [*payload.values(), group_key],
            )
