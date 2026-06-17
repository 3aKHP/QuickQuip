from __future__ import annotations

import json
import logging
from pathlib import Path

try:
    import nonebot
    from nonebot_plugin_apscheduler import scheduler
except (ModuleNotFoundError, ValueError):
    nonebot = None
    scheduler = None

from quickquip.app.message_pipeline import (
    _ensure_llm_bindings,
    get_llm_service,
    is_admin as _is_admin,
    rate_limiter,
    rule_switch,
    stats_tracker,
    strip_command_name as _strip_command_name,
)
from quickquip.chat.awakening import get_config, run_boredom_check

logger = logging.getLogger(__name__)

_RULE_NAME = "awakening_boredom"
_BOREDOM_GROUPS_PATH = Path("data/awakening_boredom_groups.json")


def _safe_group_id(group_id: int | str) -> str:
    s = str(group_id).strip()
    if not s.isdigit():
        raise ValueError(f"Invalid group_id: {group_id!r}")
    return s


class BoredomEnabledGroups:
    """Manages the opt-in set of groups with boredom awakening enabled."""

    def __init__(self, path: str | Path = _BOREDOM_GROUPS_PATH):
        self.path = Path(path)
        self._groups: set[str] = set()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            raw_groups = data.get("enabled", [])
            validated: set[str] = set()
            for g in raw_groups:
                try:
                    validated.add(_safe_group_id(g))
                except ValueError:
                    logger.warning("awakening: ignoring invalid group_id in %s: %r", self.path, g)
            self._groups = validated
        except (OSError, json.JSONDecodeError):
            self._groups = set()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump({"enabled": sorted(self._groups)}, f, ensure_ascii=False, indent=2)
            tmp.replace(self.path)
        except OSError:
            logger.warning("awakening: failed to save boredom groups to %s", self.path)
            tmp.unlink(missing_ok=True)

    def add(self, group_id: int | str) -> None:
        self._groups.add(_safe_group_id(group_id))
        self.save()

    def remove(self, group_id: int | str) -> None:
        self._groups.discard(_safe_group_id(group_id))
        self.save()

    def contains(self, group_id: int | str) -> bool:
        return _safe_group_id(group_id) in self._groups

    def all_groups(self) -> list[str]:
        return sorted(self._groups)


boredom_enabled_groups = BoredomEnabledGroups()


def _register_scheduler_jobs() -> None:
    if not scheduler:
        return
    _ensure_llm_bindings()
    cfg = get_config()
    interval = cfg.defaults.boredom_check_interval
    if interval <= 0:
        interval = 300

    from quickquip.adapters.nonebot.scheduler_plugin import record_job_result

    job_id = "awakening_boredom_check"

    async def _wrapped_boredom_check():
        try:
            if nonebot is None:
                return
            try:
                bot = nonebot.get_bot()
            except Exception:
                return
            svc = get_llm_service()
            await run_boredom_check(bot, boredom_enabled_groups, rule_switch, svc, rate_limiter, stats_tracker)
            try:
                record_job_result(job_id, True)
            except Exception:
                pass
        except Exception as exc:
            try:
                record_job_result(job_id, False, str(exc)[:500])
            except Exception:
                pass
            raise

    scheduler.add_job(
        _wrapped_boredom_check,
        "interval",
        seconds=interval,
        id=job_id,
        replace_existing=True,
    )
    logger.info("awakening: boredom check job registered (interval=%ds)", interval)


def register_awakening_commands(on_command) -> None:
    cmd = on_command("awakening", priority=10, block=True)

    @cmd.handle()
    async def _(event):
        if getattr(event, "group_id", None) is None:
            await cmd.finish("该命令仅支持群聊")

        group_id = event.group_id
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "awakening").strip()
        tokens = [item for item in args.split() if item]
        action = tokens[0].lower() if tokens else "status"

        cfg = get_config()
        settings = cfg.resolve_group(group_id)

        if action in {"status", "状态", ""}:
            rules = [
                ("awakening_extend", "唤醒延长"),
                ("awakening_interest", "兴趣话题"),
                ("awakening_fallback", "兜底概率"),
                ("awakening_boredom", "无聊唤醒"),
                ("awakening_relevance", "相关性唤醒"),
                ("awakening_qa", "答疑唤醒"),
            ]
            lines = ["唤醒模块状态："]
            for rule_name, label in rules:
                enabled = rule_switch.is_enabled(group_id, rule_name)
                lines.append(f"  [{('ON' if enabled else 'OFF')}] {label} ({rule_name})")

            lines.append("")
            lines.append(f"唤醒延长: {settings.extend_duration}s")
            lines.append(f"兴趣话题: {settings.interest_topics or '(未配置)'}")
            lines.append(f"兜底概率: {settings.fallback_probability}")
            lines.append(f"无聊沉寂: {settings.boredom_silence_seconds}s / 概率 {settings.boredom_probability}")
            lines.append(f"无聊检查间隔: {settings.boredom_check_interval}s")
            lines.append(f"相关性阈值: {settings.relevance_threshold} (>=1 关闭)")
            lines.append(f"答疑阈值: {settings.qa_threshold} (>=1 关闭)")
            if settings.boredom_dnd_start and settings.boredom_dnd_end:
                lines.append(f"免打扰: {settings.boredom_dnd_start}-{settings.boredom_dnd_end}")
            boredom_group = boredom_enabled_groups.contains(group_id)
            lines.append(f"无聊唤醒群启用: {'是' if boredom_group else '否'}")
            await cmd.finish("\n".join(lines))

        if action in {"on", "开启", "启用"}:
            if not _is_admin(event):
                await cmd.finish("仅管理员可执行此操作")
            if len(tokens) < 2:
                await cmd.finish("用法: /awakening on <规则名>\n可选: awakening_extend, awakening_interest, awakening_fallback, awakening_boredom, awakening_relevance, awakening_qa")
            rule_name = tokens[1]
            valid_rules = {"awakening_extend", "awakening_interest", "awakening_fallback", "awakening_boredom", "awakening_relevance", "awakening_qa"}
            if rule_name not in valid_rules:
                await cmd.finish(f"未知规则: {rule_name}")
            rule_switch.enable(group_id, rule_name)
            from quickquip.app.message_pipeline import RULE_SWITCH_PATH
            rule_switch.save(RULE_SWITCH_PATH)
            await cmd.finish(f"已启用 {rule_name}")

        if action in {"off", "关闭", "禁用"}:
            if not _is_admin(event):
                await cmd.finish("仅管理员可执行此操作")
            if len(tokens) < 2:
                await cmd.finish("用法: /awakening off <规则名>")
            rule_name = tokens[1]
            valid_rules = {"awakening_extend", "awakening_interest", "awakening_fallback", "awakening_boredom", "awakening_relevance", "awakening_qa"}
            if rule_name not in valid_rules:
                await cmd.finish(f"未知规则: {rule_name}")
            rule_switch.disable(group_id, rule_name)
            from quickquip.app.message_pipeline import RULE_SWITCH_PATH
            rule_switch.save(RULE_SWITCH_PATH)
            await cmd.finish(f"已禁用 {rule_name}")

        if action == "boredom":
            if not _is_admin(event):
                await cmd.finish("仅管理员可执行此操作")
            sub = tokens[1].lower() if len(tokens) >= 2 else ""
            if sub in {"on", "开启", "启用"}:
                boredom_enabled_groups.add(group_id)
                await cmd.finish("本群无聊唤醒已开启。")
            if sub in {"off", "关闭", "禁用"}:
                boredom_enabled_groups.remove(group_id)
                await cmd.finish("本群无聊唤醒已关闭。")
            await cmd.finish("用法: /awakening boredom on|off")

        await cmd.finish(
            "用法: /awakening <command>\n"
            "  status        — 查看状态\n"
            "  on <rule>     — 启用规则（管理员）\n"
            "  off <rule>    — 禁用规则（管理员）\n"
            "  boredom on|off — 开关无聊唤醒群启用（管理员）\n"
            "可选规则: awakening_extend, awakening_interest, awakening_fallback,\n"
            "  awakening_boredom, awakening_relevance, awakening_qa"
        )


def setup(on_command) -> None:
    _register_scheduler_jobs()
    register_awakening_commands(on_command)
