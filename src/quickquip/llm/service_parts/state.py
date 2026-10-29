from __future__ import annotations


from quickquip.llm.config import REASONING_EFFORT_CHOICES, ProviderConfig
from quickquip.llm.epoch import EpochKey
from quickquip.llm.settings import DeliveryDomain
from quickquip.llm.store_parts.agent_records import HistoryMutation


class StateMixin:
    def set_chat_enabled(self, chat_id: int | str, enabled: bool, chat_type: str = "group") -> None:
        if chat_type == "private":
            self.store.set_private_chat_active(str(chat_id), enabled)
        else:
            self._update_chat_settings(chat_id, chat_type, enabled=int(enabled))

    def _clear_session_caches(
        self, scope_key: str, evictions: dict[EpochKey, tuple[int, int]],
    ) -> None:
        """Invalidate derived state only after the persistent transition commits."""
        self._epochs.reset_scope(scope_key, store=self.store, evictions=evictions)
        self._envelope_cache.clear_scope(scope_key)
        self._skill_activations.clear_scope(scope_key)
        if self.recent_message_buffer:
            self.recent_message_buffer.clear_scope(scope_key)

    def start_private_session(self, user_id: int | str, *, preset: str = "") -> None:
        scope_key = self.build_chat_scope_key(user_id, "private")
        evictions = self._epochs.capture_scope_evictions(scope_key, self.store)
        self.store.start_private_chat_session(str(user_id))
        self._clear_session_caches(scope_key, evictions)
        self._session_presets.pop(scope_key, None)
        if preset.strip():
            self._session_presets[scope_key] = preset.strip()

    def end_private_session(self, user_id: int | str, *, save: bool = True) -> dict:
        scope_key = self.build_chat_scope_key(user_id, "private")
        settings = self.get_chat_settings(user_id, chat_type="private")
        evictions = self._epochs.capture_scope_evictions(scope_key, self.store) if not save else {}
        result = self.store.end_private_chat_session(
            str(user_id), save=save, persona_id=settings.persona_id or None,
            preset=self._session_presets.get(scope_key, ""),
        )
        self._clear_session_caches(scope_key, evictions)
        self._session_presets.pop(scope_key, None)
        return result

    def resume_private_session(self, user_id: int | str, archive_number: int | None = None) -> dict:
        scope_key = self.build_chat_scope_key(user_id, "private")
        evictions = self._epochs.capture_scope_evictions(scope_key, self.store)
        result = self.store.resume_private_chat_session(str(user_id), archive_number)
        if "error" in result:
            return result
        self._clear_session_caches(scope_key, evictions)
        self._session_presets.pop(scope_key, None)
        if result["preset"]:
            self._session_presets[scope_key] = result["preset"]
        return result

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
        return self.store.delete_archived_chat_session(str(user_id), archive_number)

    def get_session_preset(self, scope_key: str) -> str:
        return self._session_presets.get(scope_key, "")

    def set_group_enabled(self, group_id: int | str, enabled: bool) -> None:
        self.set_chat_enabled(group_id, enabled, chat_type="group")

    def set_chat_memory_enabled(
        self, chat_id: int | str, enabled: bool, chat_type: str = "group"
    ) -> None:
        self._update_chat_settings(chat_id, chat_type, memory_enabled=int(enabled))

    def set_group_memory_enabled(self, group_id: int | str, enabled: bool) -> None:
        self.set_chat_memory_enabled(group_id, enabled, chat_type="group")

    def set_chat_auto_memory_enabled(
        self, chat_id: int | str, enabled: bool | None, chat_type: str = "group"
    ) -> None:
        value = None if enabled is None else int(enabled)
        self._update_chat_settings(chat_id, chat_type, auto_memory_enabled=value)

    def set_chat_agent_delivery_enabled(
        self,
        chat_id: int | str,
        enabled: bool | None,
        chat_type: str = "group",
        domain: DeliveryDomain | str = DeliveryDomain.ALL,
    ) -> None:
        """按域写交付开关覆盖；域入参接受枚举或其字符串值，非法值抛 ValueError。"""
        domain = DeliveryDomain(domain)
        value = None if enabled is None else int(enabled)
        match domain:
            case DeliveryDomain.INTERMEDIATE:
                self._update_chat_settings(
                    chat_id, chat_type, agent_delivery_intermediate_enabled=value
                )
            case DeliveryDomain.FINAL:
                self._update_chat_settings(
                    chat_id, chat_type, agent_delivery_final_enabled=value
                )
            case DeliveryDomain.ALL:
                self._update_chat_settings(
                    chat_id, chat_type,
                    agent_delivery_intermediate_enabled=value,
                    agent_delivery_final_enabled=value,
                )

    def set_chat_reasoning_effort(
        self, chat_id: int | str, effort: str | None, chat_type: str = "group"
    ) -> None:
        """写思考档位覆盖（六档词表；None = 清除覆盖，跟随 provider 配置档）。"""
        if effort is not None:
            effort = effort.strip().lower()
            if effort not in REASONING_EFFORT_CHOICES:
                raise ValueError(
                    f"未知思考档位 {effort!r}（可用：{'/'.join(REASONING_EFFORT_CHOICES)}）"
                )
        self._update_chat_settings(chat_id, chat_type, reasoning_effort=effort)

    def set_chat_history_limit(
        self, chat_id: int | str, limit: int, chat_type: str = "group"
    ) -> None:
        self._update_chat_settings(chat_id, chat_type, history_limit=limit)

    def set_group_history_limit(self, group_id: int | str, limit: int) -> None:
        self.set_chat_history_limit(group_id, limit, chat_type="group")

    def reset_chat_history_limit(self, chat_id: int | str, chat_type: str = "group") -> None:
        self._update_chat_settings(chat_id, chat_type, history_limit=None)

    def reset_group_history_limit(self, group_id: int | str) -> None:
        self.reset_chat_history_limit(group_id, chat_type="group")

    def set_chat_model(
        self, chat_id: int | str, provider_id: str, model: str = "", chat_type: str = "group"
    ) -> str:
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

    def set_chat_persona(
        self, chat_id: int | str, persona_id: str, chat_type: str = "group"
    ) -> None:
        if persona_id not in self.config.personas:
            raise ValueError(f"未知 persona：{persona_id}")
        # persona 切换 = system 字节变化 = 该纪元键缓存全灭 = 免费重置窗口，
        # 按冷场水位挪锚点（不看 idle）。取切换前的 (provider, model) 键——
        # 被杀的正是它。换 provider/model 无需挂钩：纪元键自动开新纪元。
        settings = self.get_chat_settings(chat_id, chat_type=chat_type)
        self._update_chat_settings(chat_id, chat_type, persona_id=persona_id)
        provider = self.config.providers.get(settings.provider_id)
        if provider is not None:
            epoch_key = EpochKey(
                scope_key=self.build_chat_scope_key(chat_id, chat_type),
                provider_id=provider.id,
                model=settings.model or provider.default_model,
            )
            reset_event = self._epochs.advance_to_cold_water(
                epoch_key,
                store=self.store,
                params=self.config.resolve_epoch_params(provider),
            )
            if reset_event is not None:
                self._skill_activations.clear_scope(epoch_key.scope_key)

    def set_group_persona(self, group_id: int | str, persona_id: str) -> None:
        self.set_chat_persona(group_id, persona_id, chat_type="group")

    def set_chat_trigger_prefix(
        self, chat_id: int | str, prefix: str, chat_type: str = "group"
    ) -> None:
        prefix = prefix.strip()
        if not prefix:
            raise ValueError("触发前缀不能为空")
        self._update_chat_settings(chat_id, chat_type, trigger_prefix=prefix)

    def set_group_trigger_prefix(self, group_id: int | str, prefix: str) -> None:
        self.set_chat_trigger_prefix(group_id, prefix, chat_type="group")

    def set_chat_allow_prefix(
        self, chat_id: int | str, enabled: bool, chat_type: str = "group"
    ) -> None:
        self._update_chat_settings(chat_id, chat_type, allow_prefix=int(enabled))

    def set_group_allow_prefix(self, group_id: int | str, enabled: bool) -> None:
        self.set_chat_allow_prefix(group_id, enabled, chat_type="group")

    def set_group_allow_at(self, group_id: int | str, enabled: bool) -> None:
        self._update_chat_settings(group_id, "group", allow_at=int(enabled))

    def remember_memory(
        self,
        chat_id: int | str,
        content: str,
        chat_type: str = "group",
        *,
        content_parts: dict | None = None,
        source_role: str = "unknown",
        source_user_id: str | None = None,
        source_message_id: str | None = None,
        memory_id: int | None = None,
    ) -> int:
        scope_key = self.build_chat_scope_key(chat_id, chat_type)
        if memory_id is not None:
            item = self.store.read_memory(scope_key, memory_id)
            self.store.update_memory(
                scope_key, memory_id, version=item['version'], content=content,
                content_parts=content_parts,
                provenance={'writer': 'command', 'source_role': source_role,
                            'source_user_id': source_user_id,
                            'source_message_id': source_message_id})
            return memory_id
        memory_id = self.store.add_memory(
            scope_key,
            content.strip(),
            scope="group",
            source="manual",
            source_role=source_role,
            source_user_id=source_user_id,
            source_message_id=source_message_id,
            content_parts=content_parts,
            max_items=self.config.runtime.memory_max_items_per_group,
        )
        return memory_id

    def remember_group_memory(self, group_id: int | str, content: str) -> int:
        return self.remember_memory(group_id, content, chat_type="group")

    def list_memories(
        self, chat_id: int | str, keyword: str | None = None, chat_type: str = "group"
    ) -> list[dict[str, object]]:
        return self.store.list_memories(
            self.build_chat_scope_key(chat_id, chat_type), limit=10, keyword=keyword
        )

    def list_group_memories(
        self, group_id: int | str, keyword: str | None = None
    ) -> list[dict[str, object]]:
        return self.list_memories(group_id, keyword=keyword, chat_type="group")

    def forget_memories(self, chat_id: int | str, keyword: str, chat_type: str = "group",
                        *, literal: bool = False) -> int:
        return self.store.delete_memories(
            self.build_chat_scope_key(chat_id, chat_type), keyword.strip(), literal=literal
        )

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
            lines.append(
                f"- {provider.id} [{provider.protocol}] "
                f"默认：{provider.default_model}{suffix}"
            )
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
            header = (
                f"{provider.id} 可用模型（已禁用）："
                if not provider.enabled
                else f"{provider.id} 可用模型："
            )
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

    def format_memories(
        self, group_id: int | str, keyword: str | None = None, chat_type: str = "group",
        *, page: int = 1,
    ) -> str:
        scope = self.build_chat_scope_key(group_id, chat_type)
        memories = self.store.list_memories(scope, keyword=keyword, limit=11,
                                            offset=(max(1, page) - 1) * 10)
        if not memories:
            return f"{self._scope_subject(chat_type)}没有已保存记忆"
        lines = [f"{self._memory_label(chat_type)} · 第 {page} 页："]
        for item in memories[:10]:
            lines.append(f"- #{item['id']} {item['title']}：{item['description']}")
        if len(memories) > 10:
            lines.append(f"下一页：/memories --page {page + 1} {keyword or ''}")
        lines.append("全文：/memories --id <编号>")
        return "\n".join(lines)

    def format_memory_status(self, group_id: int | str, chat_type: str = "group") -> str:
        settings = self.get_chat_settings(group_id, chat_type=chat_type)
        total = self.store.count_memories(self.build_chat_scope_key(group_id, chat_type))
        lines = ["记忆状态"]
        lines.append(f"当前会话：{self._scope_label(chat_type)}")
        lines.append(f"记忆注入：{'ON' if settings.memory_enabled else 'OFF'}")
        lines.append(f"已存条数：{total}")
        lines.append(f"自动召回上限：{min(5, self.config.runtime.memory_limit)} 条 / 2048 token")
        lines.append(f"存储上限：{self.config.runtime.memory_max_items_per_group}")
        return "\n".join(lines)

    def clear_context(self, group_id: int | str, chat_type: str = "group") -> int:
        scope_key = self.build_chat_scope_key(group_id, chat_type)
        evictions = self._epochs.capture_scope_evictions(scope_key, self.store)
        deleted = self.store.clear_chat_session(scope_key)
        self._clear_session_caches(scope_key, evictions)
        return deleted

    def _bump_scope_generation(self, scope_key: str, mutation: str) -> None:
        """generation/revision 屏障（§4.2）：清空后迟到结果不得新建内容。"""
        _, revision = self.store.agent_scope_state(scope_key)
        self.store.mutate_history(scope_key, revision, mutation)

    def clear_group_context(self, group_id: int | str) -> int:
        return self.clear_context(group_id, chat_type="group")

    def delete_message_from_context(self, scope_key: str, message_id: str) -> bool:
        """撤回/删除入口（§9.2/§9.3）：先按 QQ receipt 定位确切 delivery。"""
        delivery = self.store.lookup_delivery(scope_key, message_id)
        if delivery is not None:
            hit = self.store.recall_delivery_chunk(scope_key, str(delivery["delivery_id"]))
            if hit:
                self._bump_scope_generation(scope_key, HistoryMutation.RECALL)
                return True
        # 兼容回退：按平台 message_id 匹配主表行（legacy 行/兼容列）。
        rows = self.store.conversation_rows_by_message_id(scope_key, message_id)
        deleted_any = False
        for row in rows:
            if row["role"] == "user":
                # 群友撤回触发消息：按整 Loop 删除处理（§9.3）。
                deleted_any = (
                    self.store.delete_loop_by_anchor(scope_key, int(row["id"])) or deleted_any
                )
            else:
                deleted_any = (
                    self.store.delete_turn_by_message_row(scope_key, int(row["id"]))
                    or deleted_any
                )
        if deleted_any:
            self._bump_scope_generation(scope_key, HistoryMutation.DELETE)
        buf_deleted = (
            self.recent_message_buffer.remove_by_message_id(scope_key, message_id)
            if self.recent_message_buffer and not delivery
            else False
        )
        return deleted_any or buf_deleted
