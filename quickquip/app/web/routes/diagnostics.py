from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quickquip.llm.config import load_llm_config
from quickquip.llm.provider import (
    LLMRequest,
    build_provider_client,
    clear_trace_entries,
    get_trace_entries,
    _TRACE_FLAG_FILE,
)
from quickquip.llm.tools import LLMConversationMessage

router = APIRouter()


class SampleRequest(BaseModel):
    provider_id: str
    model: str | None = None
    system_prompt: str = "你是一个测试助手。"
    user_prompt: str = "你好，请做一下自我介绍。"
    stream: bool = False
    max_output_tokens: int = 256


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
    config = load_llm_config("config/llm.toml")
    if config.load_error:
        return {"providers": []}
    return {
        "providers": [
            {"id": p.id, "models": p.models}
            for p in config.providers.values()
        ]
    }


# ── Trace control ────────────────────────────────────────────────────────────


@router.get("/diagnostics/trace-status")
def get_trace_status():
    return {
        "active": os.path.exists(_TRACE_FLAG_FILE) if _TRACE_FLAG_FILE else False,
        "flag_file": _TRACE_FLAG_FILE or "",
        "entry_count": len(get_trace_entries(0)),
    }


@router.post("/diagnostics/trace-status")
def set_trace_status(body: TraceToggle):
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


@router.get("/diagnostics/trace/recent")
def get_recent_traces(n: int = 20):
    n = max(1, min(n, 100))
    return {"entries": get_trace_entries(n)}


@router.post("/diagnostics/trace/clear")
def clear_traces():
    count = clear_trace_entries()
    return {"cleared": count}


# ── Sample request ───────────────────────────────────────────────────────────


@router.post("/diagnostics/sample-request")
async def run_sample_request(body: SampleRequest):
    import time

    config = load_llm_config("config/llm.toml")
    if config.load_error:
        raise HTTPException(status_code=400, detail=f"config load error: {config.load_error}")

    provider = config.providers.get(body.provider_id)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"unknown provider: {body.provider_id}")

    model = body.model or provider.default_model
    if model not in provider.models:
        raise HTTPException(status_code=400, detail=f"model {model} not available")

    try:
        client = build_provider_client(provider)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to build client: {exc}") from exc

    req = LLMRequest(
        model=model,
        system_prompt=body.system_prompt,
        messages=[LLMConversationMessage(role="user", content=body.user_prompt)],
        temperature=provider.temperature,
        max_output_tokens=body.max_output_tokens,
        allow_tool_calls=False,
    )

    t0 = time.monotonic()
    trace_was_active = False
    if _TRACE_FLAG_FILE:
        trace_was_active = os.path.exists(_TRACE_FLAG_FILE)
        try:
            Path(_TRACE_FLAG_FILE).touch()
        except OSError:
            pass
    pre_count = len(get_trace_entries(0))

    try:
        response = await client.complete(req)
    except Exception as exc:
        if _TRACE_FLAG_FILE and not trace_was_active:
            try:
                os.remove(_TRACE_FLAG_FILE)
            except (OSError, FileNotFoundError):
                pass
        raise HTTPException(status_code=502, detail=f"API call failed: {exc}") from exc
    finally:
        if _TRACE_FLAG_FILE and not trace_was_active:
            try:
                os.remove(_TRACE_FLAG_FILE)
            except (OSError, FileNotFoundError):
                pass

    elapsed_ms = (time.monotonic() - t0) * 1000
    trace_entries = get_trace_entries(200)[pre_count:]

    return {
        "text": response.text,
        "model": response.model,
        "finish_reason": response.finish_reason,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "thinking_blocks": response.thinking_blocks,
        "duration_ms": round(elapsed_ms, 1),
        "raw_traces": trace_entries,
    }


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
                matches.append({
                    "name": rule.get("name", f"rule_{rule_index}"),
                    "patterns": rule_matches,
                    "priority": int(rule.get("priority", 0)),
                })
        results.append({
            "label": sample.label,
            "text": text,
            "matched": bool(matches),
            "rules": matches[:10],
        })

    return {"samples": results}
