import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from quickquip.common.paths import RULE_SWITCH_JSON_PATH as RULE_SWITCH_PATH
from quickquip.app.web.audit import audit_logger
from quickquip.chat.rule_switch import SWITCHABLE_RULES

router = APIRouter()

_GROUP_ID_RE = re.compile(r"^\d{5,12}$")


class RuleToggle(BaseModel):
    enabled: bool


@router.get("/rules")
def get_rules():
    from quickquip.app.message_pipeline import rule_switch

    return {
        "disabled": rule_switch.to_dict(),
        "all_rules": sorted(SWITCHABLE_RULES),
    }


@router.post("/rules/{group_id}/{rule_name}")
def set_rule(group_id: str, rule_name: str, body: RuleToggle, request: Request):
    from quickquip.app.message_pipeline import rule_switch

    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=400, detail="group_id must be 5-12 digits")
    if rule_name not in SWITCHABLE_RULES:
        raise HTTPException(status_code=400, detail=f"Unknown rule: {rule_name}")
    old_enabled = rule_switch.is_enabled(group_id, rule_name)
    new_enabled = body.enabled
    if new_enabled:
        rule_switch.enable(group_id, rule_name)
    else:
        rule_switch.disable(group_id, rule_name)
    rule_switch.save(RULE_SWITCH_PATH)
    audit_logger.log(
        request,
        action="toggle",
        target_type="rule",
        target_id=f"group:{group_id}:rule:{rule_name}",
        summary_before={"enabled": old_enabled},
        summary_after={"enabled": new_enabled},
    )
    return {"ok": True}
