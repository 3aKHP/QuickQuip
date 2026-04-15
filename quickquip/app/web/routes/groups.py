from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from quickquip.app.message_pipeline import daily_enabled_groups, daily_briefing_enabled_groups

router = APIRouter()


class GroupToggle(BaseModel):
    enabled: bool


@router.get("/groups")
def get_groups():
    return {
        "summary": sorted(daily_enabled_groups.all_groups()),
        "briefing": sorted(daily_briefing_enabled_groups.all_groups()),
    }


@router.post("/groups/summary/{group_id}")
def set_summary_group(group_id: str, body: GroupToggle):
    if not group_id.isdigit():
        raise HTTPException(status_code=400, detail="group_id must be numeric")
    if body.enabled:
        daily_enabled_groups.add(group_id)
    else:
        daily_enabled_groups.remove(group_id)
    return {"ok": True}


@router.post("/groups/briefing/{group_id}")
def set_briefing_group(group_id: str, body: GroupToggle):
    if not group_id.isdigit():
        raise HTTPException(status_code=400, detail="group_id must be numeric")
    if body.enabled:
        daily_briefing_enabled_groups.add(group_id)
    else:
        daily_briefing_enabled_groups.remove(group_id)
    return {"ok": True}
