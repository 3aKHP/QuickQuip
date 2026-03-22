from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from plugins.llm_config import LLMConfig, PersonaConfig, ProviderConfig, load_llm_config
from plugins.llm_inputs import extract_llm_input, extract_llm_prompt
from plugins.llm_provider import LLMProviderError, LLMRequest, build_provider_client
from plugins.llm_store import LLMStore
from plugins.llm_vocab import VocabIndex
from plugins.tz_config import BEIJING_TIMEZONE


CONFIG_PATH = Path("config/llm.toml")
DB_PATH = Path("data/llm.db")
VOCAB_PATH = Path("dev/llm_about/vocab.yaml")
LLM_RULE_NAME = "llm_chat"
MAX_TRIGGER_CONTEXT_MESSAGES = 20
MAX_CONVERSATION_HISTORY_MESSAGES = 20
MAX_STORED_CONVERSATION_MESSAGES = 20
MAX_MEMORY_RETRIEVAL_ITEMS = 8
MAX_STORED_MEMORY_ITEMS = 200


@dataclass(slots=True)
class ResolvedGroupSettings:
    enabled: bool
    memory_enabled: bool
    provider_id: str
    model: str
    persona_id: str
    trigger_prefix: str
    allow_prefix: bool
    allow_at: bool
class LLMService:
    def __init__(
        self,
        config_path: str | Path = CONFIG_PATH,
        db_path: str | Path = DB_PATH,
        vocab_path: str | Path = VOCAB_PATH,
    ):
        self.config_path = Path(config_path)
        self.store = LLMStore(db_path)
        self.vocab_path = Path(vocab_path)
        self.config = load_llm_config(self.config_path)
        self.vocab = VocabIndex.from_file(self.vocab_path)

    def reload_config(self) -> LLMConfig:
        self.config = load_llm_config(self.config_path)
        self.vocab = VocabIndex.from_file(self.vocab_path)
        return self.config

    def get_group_settings(self, group_id: int | str) -> ResolvedGroupSettings:
        overrides = self.store.get_group_settings(group_id)
        provider_id = overrides.provider_id or self.config.runtime.default_provider or ""
        provider = self.config.providers.get(provider_id)
        model = overrides.model or (provider.default_model if provider else "")

        return ResolvedGroupSettings(
            enabled=overrides.enabled if overrides.enabled is not None else self.config.runtime.enabled,
            memory_enabled=(
                overrides.memory_enabled
                if overrides.memory_enabled is not None
                else self.config.runtime.memory_enabled
            ),
            provider_id=provider_id,
            model=model,
            persona_id=overrides.persona_id or self.config.runtime.default_persona or "",
            trigger_prefix=overrides.trigger_prefix or self.config.triggers.default_prefix,
            allow_prefix=(
                overrides.allow_prefix
                if overrides.allow_prefix is not None
                else self.config.triggers.allow_prefix
            ),
            allow_at=overrides.allow_at if overrides.allow_at is not None else self.config.triggers.allow_at,
        )

    def list_providers(self) -> list[ProviderConfig]:
        return list(self.config.providers.values())

    def list_personas(self) -> list[PersonaConfig]:
        return list(self.config.personas.values())

    def format_status(self, group_id: int | str) -> str:
        settings = self.get_group_settings(group_id)
        lines = ["LLM 状态"]
        if self.config.load_error:
            lines.append(f"配置：{self.config.load_error}")
            return "\n".join(lines)

        lines.append(f"总开关：{'ON' if settings.enabled else 'OFF'}")
        lines.append(f"记忆注入：{'ON' if settings.memory_enabled else 'OFF'}")
        lines.append(f"Provider：{settings.provider_id}")
        lines.append(f"Model：{settings.model}")
        lines.append(f"Persona：{settings.persona_id}")
        lines.append(f"前缀触发：{'ON' if settings.allow_prefix else 'OFF'} ({settings.trigger_prefix})")
        lines.append(f"艾特触发：{'ON' if settings.allow_at else 'OFF'}")
        lines.append(f"临时上下文：触发前最多 {MAX_TRIGGER_CONTEXT_MESSAGES} 条群消息")
        return "\n".join(lines)

    def format_current(self, group_id: int | str) -> str:
        settings = self.get_group_settings(group_id)
        lines = ["LLM 当前配置"]
        if self.config.load_error:
            lines.append(f"配置：{self.config.load_error}")
            return "\n".join(lines)

        lines.append(f"总开关：{'ON' if settings.enabled else 'OFF'}")
        lines.append(f"记忆注入：{'ON' if settings.memory_enabled else 'OFF'}")
        lines.append(f"Provider：{settings.provider_id}")
        lines.append(f"Model：{settings.model}")
        lines.append(f"Persona：{settings.persona_id}")
        lines.append(f"前缀触发：{'ON' if settings.allow_prefix else 'OFF'} ({settings.trigger_prefix})")
        lines.append(f"艾特触发：{'ON' if settings.allow_at else 'OFF'}")
        lines.append(
            f"短期会话：已存 {self.store.count_conversation_messages(group_id)} 条 / 上限 {MAX_STORED_CONVERSATION_MESSAGES} 条"
        )
        lines.append(
            f"长期记忆：已存 {self.store.count_memories(group_id)} 条 / 上限 {MAX_STORED_MEMORY_ITEMS} 条"
        )
        lines.append(f"临时上下文：仅触发当下向前最多 {MAX_TRIGGER_CONTEXT_MESSAGES} 条群消息")
        return "\n".join(lines)

    def set_group_enabled(self, group_id: int | str, enabled: bool) -> None:
        self.store.update_group_settings(group_id, enabled=int(enabled))

    def set_group_memory_enabled(self, group_id: int | str, enabled: bool) -> None:
        self.store.update_group_settings(group_id, memory_enabled=int(enabled))

    def set_group_model(self, group_id: int | str, provider_id: str, model: str) -> str:
        provider = self.config.providers.get(provider_id)
        if provider is None:
            raise ValueError(f"未知 provider：{provider_id}")
        if model not in provider.models:
            raise ValueError(f"provider {provider_id} 未声明模型：{model}")
        self.store.update_group_settings(group_id, provider_id=provider_id, model=model)
        return model

    def set_group_persona(self, group_id: int | str, persona_id: str) -> None:
        if persona_id not in self.config.personas:
            raise ValueError(f"未知 persona：{persona_id}")
        self.store.update_group_settings(group_id, persona_id=persona_id)

    def set_group_trigger_prefix(self, group_id: int | str, prefix: str) -> None:
        prefix = prefix.strip()
        if not prefix:
            raise ValueError("触发前缀不能为空")
        self.store.update_group_settings(group_id, trigger_prefix=prefix)

    def set_group_allow_prefix(self, group_id: int | str, enabled: bool) -> None:
        self.store.update_group_settings(group_id, allow_prefix=int(enabled))

    def set_group_allow_at(self, group_id: int | str, enabled: bool) -> None:
        self.store.update_group_settings(group_id, allow_at=int(enabled))

    def remember_group_memory(self, group_id: int | str, content: str) -> int:
        memory_id = self.store.add_memory(group_id, content.strip(), scope="group", source="manual")
        self.store.prune_memories(
            group_id,
            min(self.config.runtime.memory_max_items_per_group, MAX_STORED_MEMORY_ITEMS),
        )
        return memory_id

    def list_group_memories(self, group_id: int | str, keyword: str | None = None) -> list[dict[str, object]]:
        return self.store.list_memories(group_id, limit=10, keyword=keyword)

    def forget_group_memories(self, group_id: int | str, keyword: str) -> int:
        return self.store.delete_memories(group_id, keyword.strip())

    def format_providers(self) -> str:
        if self.config.load_error:
            return f"LLM 配置不可用：{self.config.load_error}"
        lines = ["可用 Providers："]
        for provider in self.list_providers():
            lines.append(f"- {provider.id} [{provider.protocol}] 默认模型：{provider.default_model}")
        return "\n".join(lines)

    def format_models(self, provider_id: str | None = None) -> str:
        if self.config.load_error:
            return f"LLM 配置不可用：{self.config.load_error}"
        if provider_id:
            provider = self.config.providers.get(provider_id)
            if provider is None:
                return f"未知 provider：{provider_id}"
            return "\n".join([f"{provider.id} 可用模型：", *[f"- {model}" for model in provider.models]])

        lines = ["可用模型："]
        for provider in self.list_providers():
            lines.append(f"[{provider.id}]")
            lines.extend(f"- {model}" for model in provider.models)
        return "\n".join(lines)

    def format_personas(self) -> str:
        if self.config.load_error:
            return f"LLM 配置不可用：{self.config.load_error}"
        lines = ["可用人格："]
        for persona in self.list_personas():
            lines.append(f"- {persona.id}：{persona.display_name}")
        return "\n".join(lines)

    def format_memories(self, group_id: int | str, keyword: str | None = None) -> str:
        memories = self.list_group_memories(group_id, keyword=keyword)
        if not memories:
            return "当前群没有已保存记忆"
        lines = ["当前群记忆："]
        for item in memories:
            lines.append(f"- #{item['id']} {item['content']}")
        return "\n".join(lines)

    def format_memory_status(self, group_id: int | str) -> str:
        settings = self.get_group_settings(group_id)
        total = self.store.count_memories(group_id)
        lines = ["记忆状态"]
        lines.append(f"记忆注入：{'ON' if settings.memory_enabled else 'OFF'}")
        lines.append(f"已存条数：{total}")
        lines.append(f"检索上限：{MAX_MEMORY_RETRIEVAL_ITEMS}")
        lines.append(f"存储上限：{MAX_STORED_MEMORY_ITEMS}")
        return "\n".join(lines)

    def clear_group_context(self, group_id: int | str) -> int:
        return self.store.clear_conversation_messages(group_id)

    def _build_system_prompt(
        self,
        persona: PersonaConfig,
        group_id: int | str,
        sender_name: str,
        prompt: str,
        memories: list[dict[str, object]],
    ) -> str:
        now_cst = datetime.now(ZoneInfo(BEIJING_TIMEZONE))
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

        lines = [persona.system_prompt.strip()]
        if persona.style_prompt.strip():
            lines.append(persona.style_prompt.strip())

        lines.append("当前元数据：")
        lines.append(f"- 当前北京时间：{now_cst:%Y-%m-%d %H:%M}")
        lines.append(f"- 当前星期：{weekday_names[now_cst.weekday()]}")
        lines.append(f"当前群号：{group_id}")
        lines.append(f"当前提问者昵称：{sender_name}")
        if memories:
            lines.append("以下是与当前群聊相关的持久记忆，仅在确实相关时参考：")
            for index, memory in enumerate(memories, 1):
                lines.append(f"{index}. {memory['content']}")

        vocab_lines: list[str] = []
        vocab_matches = self.vocab.find_matches(prompt)
        if vocab_matches:
            vocab_lines.append("以下词表命中仅用于帮助你做称呼消歧，不要机械复读：")
            for item in vocab_matches:
                line = f"- {item.alias} 通常指 {item.name}"
                if item.note:
                    line += f"；注意：{item.note}"
                vocab_lines.append(line)

        glossary_matches = self.vocab.find_glossary(prompt)
        if glossary_matches:
            if not vocab_lines:
                vocab_lines.append("以下黑话解释仅在当前话题相关时参考：")
            else:
                vocab_lines.append("以下黑话解释仅在当前话题相关时参考：")
            for term, meaning in glossary_matches:
                vocab_lines.append(f"- {term}：{meaning}")

        if vocab_lines:
            lines.append("\n".join(vocab_lines))
        return "\n\n".join(line for line in lines if line)

    def _normalize_history(
        self,
        history: list[dict[str, str]],
        recent_messages: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        if recent_messages:
            lines = ["以下是本次触发前，当前群里最近的消息，仅供理解上下文："]
            for index, item in enumerate(recent_messages[-MAX_TRIGGER_CONTEXT_MESSAGES:], 1):
                sender_name = item["sender_name"].strip() or item["user_id"]
                lines.append(f"{index}. {sender_name}：{item['text']}")
            normalized.append({"role": "user", "content": "\n".join(lines)})

        normalized.extend([
            {"role": item["role"], "content": item["content"]}
            for item in history
            if item["role"] in {"user", "assistant"} and item["content"].strip()
        ])
        return normalized

    async def generate_reply(
        self,
        *,
        group_id: int | str,
        user_id: int | str,
        sender_name: str,
        prompt: str,
        image_urls: list[str] | None = None,
        recent_messages: list[dict[str, str]] | None = None,
    ) -> dict[str, str]:
        prompt = prompt.strip()
        normalized_image_urls = [url for url in (image_urls or []) if url.strip()]
        if not prompt and normalized_image_urls:
            prompt = "请描述这张图片，并优先回答群友最可能想知道的内容。"

        if not prompt:
            return {
                "reply": self.config.triggers.empty_prompt_reply,
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        if self.config.load_error:
            return {
                "reply": f"LLM 配置不可用：{self.config.load_error}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        settings = self.get_group_settings(group_id)
        if not settings.enabled:
            return {
                "reply": "本群 LLM 已关闭。",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        provider = self.config.providers.get(settings.provider_id)
        if provider is None:
            return {
                "reply": f"当前 provider 不存在：{settings.provider_id}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        persona = self.config.personas.get(settings.persona_id)
        if persona is None:
            return {
                "reply": f"当前 persona 不存在：{settings.persona_id}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        trimmed_prompt = prompt[: self.config.runtime.max_prompt_chars]
        history = self.store.list_recent_conversation_messages(
            group_id,
            min(self.config.runtime.history_limit, MAX_CONVERSATION_HISTORY_MESSAGES),
        )
        memories: list[dict[str, object]] = []
        if settings.memory_enabled:
            memories = self.store.search_memories(
                group_id,
                user_id=user_id,
                query=trimmed_prompt,
                limit=min(self.config.runtime.memory_limit, MAX_MEMORY_RETRIEVAL_ITEMS),
            )
        system_prompt = self._build_system_prompt(
            persona,
            group_id,
            sender_name,
            trimmed_prompt,
            memories,
        )
        request = LLMRequest(
            model=settings.model or provider.default_model,
            system_prompt=system_prompt,
            history_messages=self._normalize_history(history, recent_messages=recent_messages),
            prompt=trimmed_prompt,
            image_urls=normalized_image_urls,
            temperature=provider.temperature,
            max_output_tokens=provider.max_output_tokens,
        )

        try:
            response = await build_provider_client(provider).complete(request)
        except LLMProviderError as exc:
            return {
                "reply": f"LLM 调用失败：{exc}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }
        except Exception as exc:
            return {
                "reply": f"LLM 调用异常：{exc}",
                "rate_limit_key": LLM_RULE_NAME,
                "rule_name": LLM_RULE_NAME,
            }

        text = re.sub(r"\n{3,}", "\n\n", response.text).strip()
        if not text:
            text = "模型没有返回可显示的文本。"

        self.store.append_conversation_message(group_id, user_id, "user", trimmed_prompt)
        self.store.append_conversation_message(group_id, None, "assistant", text)
        self.store.prune_conversation_messages(
            group_id,
            min(self.config.runtime.history_max_messages_per_group, MAX_STORED_CONVERSATION_MESSAGES),
        )

        return {
            "reply": text,
            "rate_limit_key": LLM_RULE_NAME,
            "rule_name": LLM_RULE_NAME,
        }


llm_service = LLMService()
