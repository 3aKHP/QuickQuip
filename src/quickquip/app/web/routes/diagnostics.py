from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quickquip.llm.config_service import get_config_service
from quickquip.app.web.routes.llm_configuration import ConfigurationRoute, ProbeBody
from quickquip.llm.provider import trace_store, _TRACE_FLAG_FILE

router = APIRouter(route_class=ConfigurationRoute)


class SampleRequest(BaseModel):
    provider_id: str
    model: str | None = None
    system_prompt: str = "你是一个测试助手。"
    user_prompt: str = "你好，请做一下自我介绍。"
    stream: bool = False
    max_output_tokens: int = Field(default=256, ge=1, le=16384)
    source: str | int = "published"
    request_id: str = Field(min_length=1, max_length=128)


class TraceToggle(BaseModel):
    enabled: bool


class RegressionSample(BaseModel):
    text: str
    label: str = ""


class RegressionRequest(BaseModel):
    samples: list[RegressionSample] = Field(min_length=1, max_length=20)


# ── Providers ────────────────────────────────────────────────────────────────


@router.get("/diagnostics/providers")
def get_diagnostics_providers():
    snapshot = get_config_service().read("published")
    document = snapshot["document"]
    return {
        "revision": snapshot["revision"],
        "providers": [
            {"id": p["id"], "default_model": p["default_model"],
             "models": [m["model"] for m in p["models"] if m["enabled"]]}
            for p in document["providers"]
            if p["enabled"]
        ]
    }


@router.post("/diagnostics/providers/probe", status_code=202)
def probe_providers(body: ProbeBody):
    result = get_config_service().probe(body.source, body.provider_id, body.model, body.request_id)
    return {**result, "may_charge": True, "automatic_retry": False}


# ── Trace control ────────────────────────────────────────────────────────────


@router.get("/diagnostics/trace-status")
def get_trace_status():
    """Report the global Trace switch and current indexed storage state."""

    return {
        "active": os.path.exists(_TRACE_FLAG_FILE) if _TRACE_FLAG_FILE else False,
        "flag_file": _TRACE_FLAG_FILE or "",
        "entry_count": trace_store.count_calls(),
        "latest_event_id": trace_store.latest_event_id(),
        "storage_bytes": trace_store.storage_bytes(),
    }


@router.post("/diagnostics/trace-status")
def set_trace_status(body: TraceToggle):
    """Toggle persistent LLM HTTP tracing for administrator diagnostics."""

    if not _TRACE_FLAG_FILE:
        raise HTTPException(status_code=400, detail="LLM_TRACE_FLAG_FILE env not set")
    flag_path = Path(_TRACE_FLAG_FILE)
    if body.enabled:
        flag_path.touch()
    else:
        try:
            os.remove(flag_path)
        except FileNotFoundError:
            pass
    return {"active": body.enabled}


@router.post("/diagnostics/trace/clear")
def clear_traces():
    """Clear all stored LLM HTTP traces on an explicit administrator request."""

    count = trace_store.clear()
    return {"cleared": count}


# ── Sample request ───────────────────────────────────────────────────────────


@router.post("/diagnostics/sample-request", status_code=202)
def run_sample_request(body: SampleRequest):
    service = get_config_service()
    document = service.read(body.source)["document"]
    provider = next((p for p in document["providers"] if p["id"] == body.provider_id), None)
    from quickquip.llm.config_document import ConfigError

    if provider is None:
        raise ConfigError("dependency_conflict", "Unknown provider", field_path="provider_id")
    result = service.probe(
        body.source,
        body.provider_id,
        body.model or provider["default_model"],
        body.request_id,
        body.model_dump(exclude={"source", "request_id"}),
    )
    return {**result, "may_charge": True, "automatic_retry": False}


# ── Regression test ──────────────────────────────────────────────────────────


@router.post("/diagnostics/regression")
def run_regression(body: RegressionRequest):
    from quickquip.chat.config import TEXT_REPLY_RULES
    from quickquip.chat.text_rules import _COMPILED_PATTERNS, is_rule_match_allowed

    if not TEXT_REPLY_RULES:
        return {"samples": []}

    results: list[dict[str, Any]] = []
    for sample in body.samples:
        text = sample.text.strip()
        if not text:
            continue
        matches: list[dict[str, Any]] = []
        for rule_index, rule in enumerate(TEXT_REPLY_RULES):
            rule_matches = []
            for compiled in _COMPILED_PATTERNS[rule_index]:
                m = compiled.search(text)
                if m and is_rule_match_allowed(rule, m):
                    rule_matches.append(compiled.pattern)
            if rule_matches:
                matches.append(
                    {
                        "name": rule.get("name", f"rule_{rule_index}"),
                        "patterns": rule_matches,
                        "priority": int(rule.get("priority", 0)),
                    }
                )
        results.append(
            {
                "label": sample.label,
                "text": text,
                "matched": bool(matches),
                "rules": matches[:10],
            }
        )

    return {"samples": results}
