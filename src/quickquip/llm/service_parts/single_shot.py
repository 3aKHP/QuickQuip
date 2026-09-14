"""STS 一次性生成入口（defectify / turmfluch / card_le_nearest）的薄编排 mixin。

差异点束（spec 常量 + response parser）与三个入口方法自 ``service.py``
原样下沉；共享管线本体在 ``quickquip.llm.single_shot``。patch 点
（``build_provider_client`` / ``_get_sensitive_filter``）仍由
``quickquip.llm.service`` 模块命名空间提供，方法内函数级导入现取。
"""
from __future__ import annotations

from typing import Any

from quickquip.llm.single_shot import (
    CommandSingleShotSpec,
    run_card_le_nearest,
    run_command_single_shot,
)
from quickquip.sts.config import (
    DEFECTIFY_RATE_LIMIT_KEY,
    DEFECTIFY_RULE_NAME,
    TURMFLUCH_RATE_LIMIT_KEY,
    TURMFLUCH_RULE_NAME,
)
from quickquip.sts.formulas.card_le.parsing import extract_card_le_name
from quickquip.sts.formulas.card_le.prompting import build_turmfluch_prompt
from quickquip.sts.formulas.defectify.prompting import build_defectify_prompt


def _defectify_reply_text(raw_text: str) -> str | None:
    return raw_text or None


def _turmfluch_reply_text(raw_text: str) -> str | None:
    name = extract_card_le_name(raw_text)
    if name is None:
        return None
    return f"{name}了"


# 一次性生成入口的差异点束；共享管线本体在 quickquip.llm.single_shot
_DEFECTIFY_SPEC = CommandSingleShotSpec(
    rate_limit_key=DEFECTIFY_RATE_LIMIT_KEY,
    rule_name=DEFECTIFY_RULE_NAME,
    usage_reply="用法：/defectify <文字>，也可以在命令里附图，或引用一条消息/图片后直接发送 /defectify。",
    invalid_reply="模型没有返回可显示的文本。",
    temperature=0.9,
    input_channel="defectify_input",
    output_channel="defectify_output",
    usage_scope_name="defectify",
    prompt_builder=build_defectify_prompt,
    response_parser=_defectify_reply_text,
)
_TURMFLUCH_SPEC = CommandSingleShotSpec(
    rate_limit_key=TURMFLUCH_RATE_LIMIT_KEY,
    rule_name=TURMFLUCH_RULE_NAME,
    usage_reply="用法：/turmfluch <文字>，也可以在命令里附图，或引用一条消息/图片后直接发送 /turmfluch。",
    invalid_reply="模型没有返回合法的卡牌/遗物名。",
    temperature=0.7,
    input_channel="turmfluch_input",
    output_channel="turmfluch_output",
    usage_scope_name="turmfluch",
    prompt_builder=build_turmfluch_prompt,
    response_parser=_turmfluch_reply_text,
    log_label="/turmfluch",
)


class SingleShotEntriesMixin:
    """defectify / turmfluch / card_le_nearest 的命令入口与被动入口。"""

    async def generate_defectify_reply(
        self,
        *,
        chat_id: int | str,
        chat_type: str,
        prompt: str,
        image_urls: list[str] | None = None,
        quoted_text: str = "",
        quoted_image_urls: list[str] | None = None,
        quoted_sender_name: str = "",
        quoted_user_id: str = "",
    ) -> dict[str, str]:
        # 薄编排：管线本体在 quickquip.llm.single_shot。patch 点
        # （build_provider_client / _get_sensitive_filter）绑定在 service 模块
        # 命名空间，此处函数内导入现取，保持 quickquip.llm.service.* patch 语义。
        from quickquip.llm import service as _service
        return await run_command_single_shot(
            spec=_DEFECTIFY_SPEC,
            config=self.config,
            chat_id=chat_id,
            resolve_scope_key=lambda: self.build_chat_scope_key(chat_id, chat_type),
            resolve_settings=lambda: self.get_chat_settings(chat_id, chat_type=chat_type),
            get_sensitive=_service._get_sensitive_filter,
            client_builder=_service.build_provider_client,
            merge_image_urls=self._merge_image_urls,
            prompt=prompt,
            image_urls=image_urls,
            quoted_text=quoted_text,
            quoted_image_urls=quoted_image_urls,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
        )

    async def generate_turmfluch_reply(
        self,
        *,
        chat_id: int | str,
        chat_type: str,
        prompt: str,
        image_urls: list[str] | None = None,
        quoted_text: str = "",
        quoted_image_urls: list[str] | None = None,
        quoted_sender_name: str = "",
        quoted_user_id: str = "",
    ) -> dict[str, Any]:
        """/turmfluch 命令：把输入提炼成一句「<卡牌或遗物名>了」。"""
        # 薄编排：管线本体在 quickquip.llm.single_shot。patch 点
        # （build_provider_client / _get_sensitive_filter）绑定在 service 模块
        # 命名空间，此处函数内导入现取，保持 quickquip.llm.service.* patch 语义。
        from quickquip.llm import service as _service
        return await run_command_single_shot(
            spec=_TURMFLUCH_SPEC,
            config=self.config,
            chat_id=chat_id,
            resolve_scope_key=lambda: self.build_chat_scope_key(chat_id, chat_type),
            resolve_settings=lambda: self.get_chat_settings(chat_id, chat_type=chat_type),
            get_sensitive=_service._get_sensitive_filter,
            client_builder=_service.build_provider_client,
            merge_image_urls=self._merge_image_urls,
            prompt=prompt,
            image_urls=image_urls,
            quoted_text=quoted_text,
            quoted_image_urls=quoted_image_urls,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
        )

    async def generate_card_le_nearest(
        self,
        *,
        captured: str,
        chat_id: int | str,
        chat_type: str,
    ) -> dict | None:
        """被动路径：群友说的「{captured}了」里的 captured 不是合法名时，找最近的
        真名，返回 ``{"reply": "名了", ...}``；无合法结果返回 None。

        走 ``[triggers.quick_judge]`` 配置的专用便宜模型，不走群主模型。
        """
        # 薄编排：管线本体在 quickquip.llm.single_shot。patch 点
        # （build_provider_client / _get_sensitive_filter）绑定在 service 模块
        # 命名空间，此处函数内导入现取，保持 quickquip.llm.service.* patch 语义。
        from quickquip.llm import service as _service
        return await run_card_le_nearest(
            config=self.config,
            chat_id=chat_id,
            resolve_scope_key=lambda: self.build_chat_scope_key(chat_id, chat_type),
            get_sensitive=_service._get_sensitive_filter,
            client_builder=_service.build_provider_client,
            captured=captured,
        )
