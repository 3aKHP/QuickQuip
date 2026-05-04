import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from quickquip.app.message_pipeline import daily_enabled_groups, daily_briefing_enabled_groups, stats_tracker
from quickquip.app.web.audit import audit_logger

router = APIRouter()

_GROUP_ID_RE = re.compile(r"^\d{5,12}$")


def _validate_group_id(group_id: str) -> None:
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=400, detail="group_id must be 5-12 digits")


class GroupToggle(BaseModel):
    enabled: bool


@router.get("/groups/known")
def get_known_groups():
    return {"groups": sorted(stats_tracker.to_dict().keys())}


@router.get("/groups")
def get_groups():
    return {
        "summary": sorted(daily_enabled_groups.all_groups()),
        "briefing": sorted(daily_briefing_enabled_groups.all_groups()),
    }


@router.post("/groups/summary/{group_id}")
def set_summary_group(group_id: str, body: GroupToggle, request: Request):
    _validate_group_id(group_id)
    if body.enabled:
        daily_enabled_groups.add(group_id)
    else:
        daily_enabled_groups.remove(group_id)
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
    if body.enabled:
        daily_briefing_enabled_groups.add(group_id)
    else:
        daily_briefing_enabled_groups.remove(group_id)
    audit_logger.log(
        request,
        action="create" if body.enabled else "delete",
        target_type="group",
        target_id=f"briefing:{group_id}",
    )
    return {"ok": True}
