from __future__ import annotations

from quickquip.llm.config import ProviderConfig
from quickquip.llm.service_parts.constants import MAX_MEMORY_RETRIEVAL_ITEMS, MAX_STORED_MEMORY_ITEMS


class StateMixin:
    def set_chat_enabled(self, chat_id: int | str, enabled: bool, chat_type: str = "group") -> None:
        self._update_chat_settings(chat_id, chat_type, enabled=int(enabled))

    def start_private_session(self, user_id: int | str, *, preset: str = "") -> None:
        scope_key = self.build_chat_scope_key(user_id, "private")
        self.clear_context(user_id, chat_type="private")
        self._session_presets.pop(scope_key, None)
        self.set_chat_enabled(user_id, True, chat_type="private")
        if preset.strip():
            self._session_presets[scope_key] = preset.strip()

    def end_private_session(self, user_id: int | str, *, save: bool = True) -> dict:
        scope_key = self.build_chat_scope_key(user_id, "private")
        user_id_str = str(user_id)
        msg_count = self.store.count_conversation_messages(scope_key)
        archive_number = None

        if save and msg_count > 0:
            archive_number = self.store.get_next_archive_number(user_id_str)
            settings = self.get_chat_settings(user_id, chat_type="private")
            preset = self._session_presets.get(scope_key, "")
            created_at = self.store.get_earliest_message_time(scope_key)
            self.store.create_session_archive(
                user_id_str,
                archive_number,
                persona_id=settings.persona_id or None,
                preset=preset or None,
                message_count=msg_count,
                created_at=created_at,
            )
            self.store.archive_conversation_messages(user_id_str, archive_number)
        else:
            self.store.clear_conversation_messages(scope_key)

        self.set_chat_enabled(user_id, False, chat_type="private")
        self._session_presets.pop(scope_key, None)
        return {"deleted": msg_count, "archive_number": archive_number}

    def resume_private_session(self, user_id: int | str, archive_number: int | None = None) -> dict:
        user_id_str = str(user_id)
        if archive_number is None:
            archive_number = self.store.get_latest_archive_number(user_id_str)
            if archive_number is None:
                return {"error": "没有可恢复的存档"}

        archive = self.store.get_session_archive(user_id_str, archive_number)
        if archive is None:
            return {"error": f"存档 #{archive_number} 不存在"}

        scope_key = self.build_chat_scope_key(user_id, "private")
        current_count = self.store.count_conversation_messages(scope_key)
        if current_count > 0:
            self.store.clear_conversation_messages(scope_key)

        self.store.restore_conversation_messages(user_id_str, archive_number)
        self._session_presets.pop(scope_key, None)
        preset = archive.get("preset") or ""
        if preset:
            self._session_presets[scope_key] = preset
        self.set_chat_enabled(user_id, True, chat_type="private")
        self.store.delete_session_archive(user_id_str, archive_number)

        return {
            "archive_number": archive_number,
            "message_count": archive.get("message_count", 0),
            "preset": preset,
            "persona_id": archive.get("persona_id") or "",
        }

    def format_session_archives(self, user_id: int | str) -> str:
        archives = self.store.list_session_archives(str(user_id))
        if not archives:
            return "暂无存档"
        lines = ["存档列表："]
        for a in reversed(archives):
            num = a["archive_number"]
            ts = (a.get("created_at") or "")[:16].replace("T", " ")
            count = a.get("message_count", 0)
            persona = a.get("persona_id") or "default"
            line = f"  #{num}  {ts}  {count}条  人格:{persona}"
            preset = a.get("preset") or ""
            if preset:
                preview = preset[:30] + ("..." if len(preset) > 30 else "")
                line += f"  附加:{preview}"
            lines.append(line)
        return "\n".join(lines)

    def delete_session_archive_for_user(self, user_id: int | str, archive_number: int) -> bool:
        return self.store.delete_session_archive(str(user_id), archive_number)

    def get_session_preset(self, scope_key: str) -> str:
        return self._session_presets.get(scope_key, "")

    def set_group_enabled(self, group_id: int | str, enabled: bool) -> None:
        self.set_chat_enabled(group_id, enabled, chat_type="group")

    def set_chat_memory_enabled(self, chat_id: int | str, enabled: bool, chat_type: str = "group") -> None:
        self._update_chat_settings(chat_id, chat_type, memory_enabled=int(enabled))

    def set_group_memory_enabled(self, group_id: int | str, enabled: bool) -> None:
        self.set_chat_memory_enabled(group_id, enabled, chat_type="group")

    def set_chat_auto_memory_enabled(
        self, chat_id: int | str, enabled: bool | None, chat_type: str = "group"
    ) -> None:
        value = None if enabled is None else int(enabled)
        self._update_chat_settings(chat_id, chat_type, auto_memory_enabled=value)

    def set_chat_history_limit(self, chat_id: int | str, limit: int, chat_type: str = "group") -> None:
        self._update_chat_settings(chat_id, chat_type, history_limit=limit)

    def set_group_history_limit(self, group_id: int | str, limit: int) -> None:
        self.set_chat_history_limit(group_id, limit, chat_type="group")

    def reset_chat_history_limit(self, chat_id: int | str, chat_type: str = "group") -> None:
        self._update_chat_settings(chat_id, chat_type, history_limit=None)

    def reset_group_history_limit(self, group_id: int | str) -> None:
        self.reset_chat_history_limit(group_id, chat_type="group")

    def set_chat_model(self, chat_id: int | str, provider_id: str, model: str = "", chat_type: str = "group") -> str:
        provider = self.config.providers.get(provider_id)
        if provider is None:
            raise ValueError(f"未知 provider：{provider_id}")
        if not provider.enabled:
            raise ValueError(f"provider {provider_id} 已禁用（enabled = false）")
        resolved = model.strip()
        if not resolved:
            resolved = provider.default_model
        elif resolved in provider.aliases:
            resolved = provider.aliases[resolved]
        if resolved not in provider.models:
            raise ValueError(f"provider {provider_id} 未声明模型：{resolved}")
        self._update_chat_settings(chat_id, chat_type, provider_id=provider_id, model=resolved)
        return resolved

    def set_group_model(self, group_id: int | str, provider_id: str, model: str) -> str:
        return self.set_chat_model(group_id, provider_id, model, chat_type="group")

    def set_chat_persona(self, chat_id: int | str, persona_id: str, chat_type: str = "group") -> None:
        if persona_id not in self.config.personas:
            raise ValueError(f"未知 persona：{persona_id}")
        self._update_chat_settings(chat_id, chat_type, persona_id=persona_id)

    def set_group_persona(self, group_id: int | str, persona_id: str) -> None:
        self.set_chat_persona(group_id, persona_id, chat_type="group")

    def set_chat_trigger_prefix(self, chat_id: int | str, prefix: str, chat_type: str = "group") -> None:
        prefix = prefix.strip()
        if not prefix:
            raise ValueError("触发前缀不能为空")
        self._update_chat_settings(chat_id, chat_type, trigger_prefix=prefix)

    def set_group_trigger_prefix(self, group_id: int | str, prefix: str) -> None:
        self.set_chat_trigger_prefix(group_id, prefix, chat_type="group")

    def set_chat_allow_prefix(self, chat_id: int | str, enabled: bool, chat_type: str = "group") -> None:
        self._update_chat_settings(chat_id, chat_type, allow_prefix=int(enabled))

    def set_group_allow_prefix(self, group_id: int | str, enabled: bool) -> None:
        self.set_chat_allow_prefix(group_id, enabled, chat_type="group")

    def set_group_allow_at(self, group_id: int | str, enabled: bool) -> None:
        self._update_chat_settings(group_id, "group", allow_at=int(enabled))

    def remember_memory(self, chat_id: int | str, content: str, chat_type: str = "group") -> int:
        scope_key = self.build_chat_scope_key(chat_id, chat_type)
        memory_id = self.store.add_memory(scope_key, content.strip(), scope="group", source="manual")
        self.store.prune_memories(
            scope_key,
            min(self.config.runtime.memory_max_items_per_group, MAX_STORED_MEMORY_ITEMS),
        )
        return memory_id

    def remember_group_memory(self, group_id: int | str, content: str) -> int:
        return self.remember_memory(group_id, content, chat_type="group")

    def list_memories(self, chat_id: int | str, keyword: str | None = None, chat_type: str = "group") -> list[dict[str, object]]:
        return self.store.list_memories(self.build_chat_scope_key(chat_id, chat_type), limit=10, keyword=keyword)

    def list_group_memories(self, group_id: int | str, keyword: str | None = None) -> list[dict[str, object]]:
        return self.list_memories(group_id, keyword=keyword, chat_type="group")

    def forget_memories(self, chat_id: int | str, keyword: str, chat_type: str = "group") -> int:
        return self.store.delete_memories(self.build_chat_scope_key(chat_id, chat_type), keyword.strip())

    def forget_group_memories(self, group_id: int | str, keyword: str) -> int:
        return self.forget_memories(group_id, keyword, chat_type="group")

    def clear_memories(self, chat_id: int | str, chat_type: str = "group") -> int:
        return self.store.clear_memories(self.build_chat_scope_key(chat_id, chat_type))

    def clear_group_memories(self, group_id: int | str) -> int:
        return self.clear_memories(group_id, chat_type="group")

    def format_providers(self) -> str:
        if self.config.load_error:
            return f"LLM 配置不可用：{self.config.load_error}"
        lines = ["可用 Providers："]
        for provider in self.list_providers():
            note_parts = []
            if provider.aliases:
                note_parts.append(f"{len(provider.aliases)} 个别名")
            if provider.fallback_urls:
                note_parts.append(f"{len(provider.fallback_urls)} 个备用")
            suffix = f"（{', '.join(note_parts)}）" if note_parts else ""
            lines.append(f"- {provider.id} [{provider.protocol}] 默认：{provider.default_model}{suffix}")
        return "\n".join(lines)

    def format_models(self, provider_id: str | None = None) -> str:
        if self.config.load_error:
            return f"LLM 配置不可用：{self.config.load_error}"

        def _model_lines(provider: ProviderConfig) -> list[str]:
            reverse: dict[str, list[str]] = {}
            for alias, target in provider.aliases.items():
                reverse.setdefault(target, []).append(alias)
            result = []
            for model in provider.models:
                aliases = reverse.get(model)
                suffix = f"  [{', '.join(sorted(aliases))}]" if aliases else ""
                result.append(f"- {model}{suffix}")
            return result

        if provider_id:
            provider = self.config.providers.get(provider_id)
            if provider is None:
                return f"未知 provider：{provider_id}"
            header = f"{provider.id} 可用模型（已禁用）：" if not provider.enabled else f"{provider.id} 可用模型："
            return "\n".join([header, *_model_lines(provider)])

        lines = ["可用模型："]
        for provider in self.list_providers():
            lines.append(f"[{provider.id}]")
            lines.extend(_model_lines(provider))
        return "\n".join(lines)

    def format_personas(self, chat_type: str = "group") -> str:
        if self.config.load_error:
            return f"LLM 配置不可用：{self.config.load_error}"
        lines = ["可用人格："]
        for persona in self.list_personas(chat_type=chat_type):
            lines.append(f"- {persona.id}：{persona.display_name}")
        return "\n".join(lines)

    def format_memories(self, group_id: int | str, keyword: str | None = None, chat_type: str = "group") -> str:
        memories = self.list_memories(group_id, keyword=keyword, chat_type=chat_type)
        if not memories:
            return f"{self._scope_subject(chat_type)}没有已保存记忆"
        lines = [f"{self._memory_label(chat_type)}："]
        for item in memories:
            lines.append(f"- #{item['id']} {item['content']}")
        return "\n".join(lines)

    def format_memory_status(self, group_id: int | str, chat_type: str = "group") -> str:
        settings = self.get_chat_settings(group_id, chat_type=chat_type)
        total = self.store.count_memories(self.build_chat_scope_key(group_id, chat_type))
        lines = ["记忆状态"]
        lines.append(f"当前会话：{self._scope_label(chat_type)}")
        lines.append(f"记忆注入：{'ON' if settings.memory_enabled else 'OFF'}")
        lines.append(f"已存条数：{total}")
        lines.append(f"检索上限：{MAX_MEMORY_RETRIEVAL_ITEMS}")
        lines.append(f"存储上限：{MAX_STORED_MEMORY_ITEMS}")
        return "\n".join(lines)

    def clear_context(self, group_id: int | str, chat_type: str = "group") -> int:
        scope_key = self.build_chat_scope_key(group_id, chat_type)
        deleted = self.store.clear_conversation_messages(scope_key)
        # 短期上下文 = 持久会话库 + 进程内最近消息缓冲；只清前者会让
        # build_messages 继续把缓冲拼进提示词，模型仍然"看得见"历史。
        if self.recent_message_buffer:
            self.recent_message_buffer.clear_scope(scope_key)
        return deleted

    def clear_group_context(self, group_id: int | str) -> int:
        return self.clear_context(group_id, chat_type="group")

    def delete_message_from_context(self, scope_key: str, message_id: str) -> bool:
        db_deleted = self.store.delete_conversation_message_by_message_id(scope_key, message_id)
        buf_deleted = self.recent_message_buffer.remove_by_message_id(scope_key, message_id) if self.recent_message_buffer else False
        return db_deleted > 0 or buf_deleted
