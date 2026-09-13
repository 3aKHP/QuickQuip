"""无聊唤醒域：opt-in 群集合、巡检产计划与发送确认（scheduler 入口）。"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from quickquip.chat.reply_probability import roll_reply
from quickquip.common.opt_in_groups import OptInGroupSet, normalize_digit_group_id
from quickquip.common.paths import AWAKENING_BOREDOM_GROUPS_PATH
from quickquip.llm.reply_types import ReplyResult

from quickquip.chat.awakening.config import AwakeningConfig, get_config
from quickquip.chat.awakening.state import get_state
from quickquip.chat.awakening.triggers import (
    RULE_BOREDOM,
    AwakeningTriggerResult,
    build_awakening_prompt,
    check_boredom,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Narrow service interfaces (structural typing: LLMService satisfies as-is)
# ---------------------------------------------------------------------------


class GroupSettingsView(Protocol):
    enabled: bool
    persona_id: str


class LoadErrorView(Protocol):
    load_error: str | None


class GroupLLMStatusSource(Protocol):
    """群级 LLM 可用性判定的窄读取面（``LLMService`` 即满足）。"""

    @property
    def config(self) -> LoadErrorView: ...

    def get_group_settings(self, group_id: int | str) -> GroupSettingsView: ...


class BoredomGroupsView(Protocol):
    def all_groups(self) -> Iterable[str]: ...


class RuleSwitchView(Protocol):
    def is_enabled(self, group_id: int | str, rule_name: str) -> bool: ...


class RateLimiterView(Protocol):
    def allow(self, rule_name: str, user_id: str, *, group_id: int | str) -> bool: ...


class StatsRecorderView(Protocol):
    def record_trigger(self, group_id: int | str, rule_name: str) -> None: ...


class GenerateReplyFn(Protocol):
    """无聊唤醒生成调用的关键字签名（``LLMService.generate_reply`` 即满足）。"""

    async def __call__(
        self,
        *,
        group_id: int | str,
        user_id: int | str,
        sender_name: str,
        prompt: str,
        image_urls: list[str] | None = ...,
        include_recent_images: bool = ...,
        raw_user_text: str | None = ...,
        store_user_message: bool = ...,
        trigger_auto_memory: bool = ...,
        message_id: str | None = ...,
    ) -> ReplyResult: ...


class BoredomLLMSource(GroupLLMStatusSource, Protocol):
    """无聊唤醒巡检对 LLM 服务对象的全部依赖。"""

    generate_reply: GenerateReplyFn


class BoredomEnabledGroups(OptInGroupSet):
    """无聊唤醒 opt-in 群集合的唯一写入所有者。

    bot 命令路径（adapter 单例）与 Web Admin 路由共用本类；跨进程写入
    由 OptInGroupSet 的 FileLock + 锁内重读合并保证不丢更新。
    """

    log_label = "awakening"

    def __init__(self, path: str | Path = AWAKENING_BOREDOM_GROUPS_PATH) -> None:
        super().__init__(path)

    def _normalize_group_id(self, group_id: int | str) -> str:
        return normalize_digit_group_id(group_id)

    def _load_entry(self, raw: object) -> str | None:
        try:
            return normalize_digit_group_id(raw)
        except ValueError:
            logger.warning("awakening: ignoring invalid group_id in %s: %r", self.path, raw)
            return None


class BoredomReplyResult(ReplyResult, total=False):
    """生成返回形状 + 适配层交付后补写的 delivered_text 扩展键。"""

    delivered_text: str


@dataclass(slots=True)
class BoredomSendPlan:
    """一条待发送的无聊唤醒计划：策略与 LLM 生成已完成，只欠传输。

    冷却标记、bot 消息缓存与统计以发送成功为前提，由发送方在传输成功后
    调用 ``confirm_boredom_sent`` 确认；发送失败不得确认。
    """

    group_id: str
    trigger: AwakeningTriggerResult
    # 适配层在 sink 交付后会向 reply_result 补写 delivered_text（BoredomReplyResult）
    reply_result: BoredomReplyResult

    def trace_kwargs(self) -> dict[str, Any]:
        """``bot_action_trace`` 的逐字段参数（字段集与旧内联实现一致）。"""
        return {
            "trigger_kind": "awakening",
            "reason_code": RULE_BOREDOM,
            "reason_detail": self.trigger.trigger_reason,
            "rule_name": RULE_BOREDOM,
            "chat_type": "group",
            "group_id": self.group_id,
            "user_id": "boredom_timer",
            "reply_preview": self.reply_result["reply"],
            "llm_used": bool(self.reply_result.get("llm_used")),
            "provider_id": str(self.reply_result.get("provider_id", "")),
            "model": str(self.reply_result.get("model", "")),
            "source": "awakening.boredom_timer",
        }


def is_group_llm_enabled(svc: GroupLLMStatusSource, group_id: int | str) -> bool:
    """群级 LLM 可用性（配置加载成功且群开关打开）；供无聊唤醒巡检与定时消息复用。"""
    if getattr(svc.config, "load_error", None):
        return False
    try:
        settings = svc.get_group_settings(group_id)
    except Exception:
        logger.debug(
            "awakening_boredom: failed to resolve LLM settings for group %s",
            group_id,
            exc_info=True,
        )
        return False
    return bool(settings.enabled)


async def iter_boredom_send_plans(
    boredom_enabled_groups: BoredomGroupsView,
    rule_switch: RuleSwitchView,
    svc: BoredomLLMSource,
    rate_limiter: RateLimiterView | None = None,
    generate: GenerateReplyFn | None = None,
    *,
    config: AwakeningConfig | None = None,
) -> AsyncIterator[BoredomSendPlan]:
    """无聊唤醒巡检的策略与生成阶段：逐群产出待发送计划。

    纯领域流程，不触碰传输（``int(gid)`` 协议转换与消息拼装归适配层）。
    ``generate`` 由适配层注入统一生成/交付流程（携带 DeliverySink）；
    缺省回落 ``svc.generate_reply``。单群生成异常记 warning 后跳过。
    """
    cfg = config if config is not None else get_config()
    st = get_state()
    st.prune_stale()
    generate = generate or svc.generate_reply

    for gid in boredom_enabled_groups.all_groups():
        if not rule_switch.is_enabled(gid, RULE_BOREDOM):
            continue
        if not is_group_llm_enabled(svc, gid):
            continue
        settings = cfg.resolve_group(gid)
        result = check_boredom(gid, settings, st)
        if result is None:
            continue
        if not roll_reply(RULE_BOREDOM, group_id=gid):
            continue
        if rate_limiter is not None and not rate_limiter.allow(
            RULE_BOREDOM, "boredom_timer", group_id=gid
        ):
            continue
        try:
            reply_result = await generate(
                group_id=gid,
                user_id="boredom_timer",
                sender_name="系统",
                prompt=build_awakening_prompt(result),
                image_urls=[],
                include_recent_images=True,
                # 合成配对行：落库结构化诱因摘要（代码生成，不抄群聊正文；
                # 同轮 prompt 已过输入扫描，history 渲染时再 scrub 兜底），
                # 消除 history 里的 assistant 孤行；不从合成内容抽记忆
                raw_user_text=f"【自动唤醒】{result.trigger_reason or result.rule_name}"[:60],
                store_user_message=True,
                trigger_auto_memory=False,
                message_id=None,
            )
        except Exception:
            logger.warning("awakening_boredom: failed for group %s", gid, exc_info=True)
            continue
        yield BoredomSendPlan(group_id=str(gid), trigger=result, reply_result=reply_result)


def confirm_boredom_sent(
    plan: BoredomSendPlan, stats_tracker: StatsRecorderView | None = None
) -> None:
    """发送成功后的状态确认：标冷却、缓存 bot 消息、记触发统计。

    仅在传输成功后调用；发送失败时调用会错误地进入冷却。
    """
    st = get_state()
    st.mark_boredom_triggered(plan.group_id)
    visible = str(plan.reply_result.get("reply") or "").strip() or str(
        plan.reply_result.get("delivered_text") or ""
    )
    st.bot_messages.add(plan.group_id, visible)
    if stats_tracker is not None:
        stats_tracker.record_trigger(plan.group_id, RULE_BOREDOM)
    logger.info(
        "awakening_boredom: sent to group %s (%s)", plan.group_id, plan.trigger.trigger_reason
    )
