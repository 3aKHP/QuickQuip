import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from quickquip.common.paths import RULE_SWITCH_JSON_PATH as RULE_SWITCH_PATH
from quickquip.app.web.action_queue import action_queue
from quickquip.app.web.audit import audit_logger

router = APIRouter()

_GROUP_ID_RE = re.compile(r"^\d{5,12}$")


def _validate_group_id(group_id: str) -> None:
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=400, detail="group_id must be 5-12 digits")


class GroupToggle(BaseModel):
    enabled: bool


class BriefingNowBody(BaseModel):
    period: str | None = None


@router.get("/groups/known")
def get_known_groups():
    from quickquip.app.message_pipeline import stats_tracker

    return {"groups": sorted(stats_tracker.to_dict().keys())}


@router.get("/groups")
def get_groups():
    from quickquip.app.message_pipeline import (
        daily_briefing_enabled_groups,
        daily_enabled_groups,
        monthly_enabled_groups,
        weekly_enabled_groups,
    )

    return {
        "summary": sorted(daily_enabled_groups.all_groups()),
        "briefing": sorted(daily_briefing_enabled_groups.all_groups()),
        "weekly": sorted(weekly_enabled_groups.all_groups()),
        "monthly": sorted(monthly_enabled_groups.all_groups()),
    }


@router.post("/groups/summary/{group_id}")
def set_summary_group(group_id: str, body: GroupToggle, request: Request):
    _validate_group_id(group_id)
    from quickquip.app.message_pipeline import daily_enabled_groups, rule_switch

    if body.enabled:
        daily_enabled_groups.add(group_id)
        rule_switch.enable(group_id, "daily_summary")
    else:
        daily_enabled_groups.remove(group_id)
        rule_switch.disable(group_id, "daily_summary")
    rule_switch.save(RULE_SWITCH_PATH)
    audit_logger.log(
        request,
        action="create" if body.enabled else "delete",
        target_type="group",
        target_id=f"summary:{group_id}",
    )
    return {"ok": True}


@router.post("/groups/briefing/{group_id}")
def set_briefing_group(group_id: str, body: GroupToggle, request: Request):
    _validate_group_id(group_id)
    from quickquip.app.message_pipeline import daily_briefing_enabled_groups, rule_switch

    if body.enabled:
        daily_briefing_enabled_groups.add(group_id)
        rule_switch.enable(group_id, "daily_briefing")
    else:
        daily_briefing_enabled_groups.remove(group_id)
        rule_switch.disable(group_id, "daily_briefing")
    rule_switch.save(RULE_SWITCH_PATH)
    audit_logger.log(
        request,
        action="create" if body.enabled else "delete",
        target_type="group",
        target_id=f"briefing:{group_id}",
    )
    return {"ok": True}


@router.post("/groups/summary/{group_id}/now")
def run_summary_now(group_id: str, request: Request):
    _validate_group_id(group_id)
    from quickquip.app.message_pipeline import daily_enabled_groups

    if not daily_enabled_groups.contains(group_id):
        raise HTTPException(status_code=409, detail="daily summary is not enabled for this group")
    action = action_queue.enqueue("summary_now", {"group_id": group_id})
    audit_logger.log(
        request,
        action="queue",
        target_type="daily_summary",
        target_id=group_id,
        summary_after={"action_id": action["id"]},
    )
    return {"ok": True, "queued": True, "action": action}


@router.post("/groups/briefing/{group_id}/now")
def run_briefing_now(group_id: str, body: BriefingNowBody, request: Request):
    _validate_group_id(group_id)
    from quickquip.app.message_pipeline import daily_briefing_enabled_groups, rule_switch

    if not daily_briefing_enabled_groups.contains(group_id) or not rule_switch.is_enabled(group_id, "daily_briefing"):
        raise HTTPException(status_code=409, detail="daily briefing is not enabled for this group")
    from quickquip.chat.daily_briefing import normalize_period

    period = normalize_period(body.period or "") if body.period else None
    if body.period and period is None:
        raise HTTPException(status_code=422, detail="period must be morning, noon or evening")
    action = action_queue.enqueue("briefing_now", {"group_id": group_id, "period": period})
    audit_logger.log(
        request,
        action="queue",
        target_type="daily_briefing",
        target_id=f"{group_id}:{period or 'auto'}",
        summary_after={"action_id": action["id"], "period": period},
    )
    return {"ok": True, "queued": True, "action": action, "period": period}


# ── 群周报 / 群月报：按群开关 + 立即生成 ──────────────────────────────────
# 与每日总结开关对称；period 报告不接入 rule_switch，仅维护 enabled 群集合。

def _period_report_enabled_groups(period_type: str):
    from quickquip.app.message_pipeline import weekly_enabled_groups, monthly_enabled_groups
    if period_type == "weekly":
        return weekly_enabled_groups
    if period_type == "monthly":
        return monthly_enabled_groups
    raise ValueError(f"unknown period_type: {period_type!r}")


def _set_period_report_group(period_type: str, group_id: str, body: GroupToggle, request: Request) -> None:
    enabled_groups = _period_report_enabled_groups(period_type)
    if body.enabled:
        enabled_groups.add(group_id)
    else:
        enabled_groups.remove(group_id)
    audit_logger.log(
        request,
        action="create" if body.enabled else "delete",
        target_type="group",
        target_id=f"{period_type}:{group_id}",
    )


def _run_period_report_now(period_type: str, group_id: str, request: Request):
    _validate_group_id(group_id)
    enabled_groups = _period_report_enabled_groups(period_type)
    if not enabled_groups.contains(group_id):
        raise HTTPException(status_code=409, detail=f"{period_type} report is not enabled for this group")
    action = action_queue.enqueue("period_report_now", {"group_id": group_id, "period_type": period_type})
    audit_logger.log(
        request,
        action="queue",
        target_type=f"{period_type}_report",
        target_id=group_id,
        summary_after={"action_id": action["id"]},
    )
    return {"ok": True, "queued": True, "action": action}


@router.post("/groups/weekly/{group_id}")
def set_weekly_group(group_id: str, body: GroupToggle, request: Request):
    _validate_group_id(group_id)
    _set_period_report_group("weekly", group_id, body, request)
    return {"ok": True}


@router.post("/groups/monthly/{group_id}")
def set_monthly_group(group_id: str, body: GroupToggle, request: Request):
    _validate_group_id(group_id)
    _set_period_report_group("monthly", group_id, body, request)
    return {"ok": True}


@router.post("/groups/weekly/{group_id}/now")
def run_weekly_now(group_id: str, request: Request):
    return _run_period_report_now("weekly", group_id, request)


@router.post("/groups/monthly/{group_id}/now")
def run_monthly_now(group_id: str, request: Request):
    return _run_period_report_now("monthly", group_id, request)
