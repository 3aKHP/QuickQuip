"""Compatibility endpoint for revision-aware provider thinking defaults."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from quickquip.app.web.audit import audit_logger
from quickquip.app.web.routes.llm_configuration import ConfigurationRoute, _provider
from quickquip.llm.config import REASONING_EFFORT_CHOICES
from quickquip.llm.config_service import get_config_service

router = APIRouter(route_class=ConfigurationRoute)


class EffortBody(BaseModel):
    effort: str | None
    expected_draft_revision: int = Field(ge=1)

    @field_validator("effort")
    @classmethod
    def _check_effort(cls, value):
        if value not in (None, "", *REASONING_EFFORT_CHOICES):
            raise ValueError("Unknown reasoning effort")
        return value


@router.get("/llm-effort")
def get_llm_effort():
    result = get_config_service().read()
    return {
        "revision": result["revision"],
        "providers": [
            {
                "id": p["id"],
                "default_model": p["default_model"],
                "reasoning_effort": p["parameters"].get("reasoning_effort"),
            }
            for p in result["document"]["providers"]
        ],
    }


@router.put("/llm-effort/{provider_id}")
def put_llm_effort(provider_id: str, body: EffortBody, request: Request):
    def transform(document):
        _provider(document, provider_id)["parameters"]["reasoning_effort"] = body.effort

    result = get_config_service().update(body.expected_draft_revision, transform)
    audit_logger.log(
        request, action="update", target_type="llm_configuration", target_id=provider_id
    )
    return {**result, "ok": True, "effect": "saved_draft"}
