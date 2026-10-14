"""Pure Profile projection around protocol-owned request construction."""
from __future__ import annotations

from dataclasses import dataclass
import json
import platform
from typing import Any
import uuid

from quickquip.common.paths import DATA_DIR
from quickquip.llm.client_fingerprints.catalog import (
    FingerprintRuntime, header_value, resolve_profile, validate_provider_headers,
)
from quickquip.llm.client_fingerprints.identity import (
    client_version, load_install_id, load_claude_device_id, load_gemini_install_id,
)
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.client_fingerprints.body_policy import ChatBodyPolicy, project_chat_body
from quickquip.llm.client_fingerprints.claude_policy import (
    ClaudeBodyPolicy, derive_beta, project_claude_body, validate_claude_overrides,
)
from quickquip.llm.client_fingerprints.retry_context import retry_count
from quickquip.llm.client_fingerprints.gemini_policy import (
    GeminiBodyPolicy, project_gemini_body, validate_gemini_overrides,
)
from quickquip.llm.context_windows import resolve_context_window
from quickquip.llm.client_fingerprints.body_bindings import project_body_bindings
from quickquip.llm.client_fingerprints.session_projection import SESSION_BINDINGS
from quickquip.llm.client_fingerprints.trace_context import (
    ATTEMPT_BINDINGS, attempt_bindings, current_request,
)


def detect_stainless_os() -> str:
    system = platform.system()
    return {"Darwin": "MacOS"}.get(system, system or "Linux")


def assemble_headers(config, request, protocol_headers: dict[str, str]) -> dict[str, str]:
    runtime = config.fingerprint_runtime or FingerprintRuntime(
        resolve_profile(config.client_fingerprint, config.protocol), "", DATA_DIR,
    )
    profile = runtime.profile
    protocol = profile.for_protocol(config.protocol)
    validate_provider_headers(config.headers, profile=profile, protocol=config.protocol)
    if runtime.profile.id != config.client_fingerprint:
        raise ConfigError(
            "invalid_profile", "Profile selection does not match its runtime snapshot",
        )
    values = {"stainless_os": detect_stainless_os(),
              "timeout_seconds": format(config.timeout_seconds, "g")}
    sources = {v for _, v in (*profile.bindings, *protocol.bindings)}
    values.update({source: build(request, runtime.data_dir)
                   for source, build in SESSION_BINDINGS.items() if source in sources})
    if "gemini_cli_install_id" in sources:
        values["gemini_cli_install_id"] = load_gemini_install_id(
            runtime.data_dir, runtime.gemini_cli_install_id,
        )
    if profile.id == "quickquip":
        try:
            epoch = uuid.UUID(request.epoch_id) if request.epoch_id else None
        except (ValueError, AttributeError, TypeError):
            epoch = None
        if epoch is None or epoch.version != 4:
            raise ConfigError(
                "missing_epoch_identity", "QuickQuip Profile requires an epoch UUIDv4",
            )
        values.update(install_id=load_install_id(runtime.data_dir), epoch_id=str(epoch),
                      cluster_id=runtime.cluster, client_version=client_version())
    headers = dict(protocol_headers)
    default_ua = ""
    for key, value in (*profile.headers, *protocol.headers):
        if key.lower() == "user-agent":
            default_ua = value
        else:
            headers[key] = value
    for key, source in (*profile.bindings, *protocol.bindings):
        if source in (*ATTEMPT_BINDINGS, "retry_count"):
            continue
        value = values[source]
        if value:
            headers[key] = header_value(value, key)
    if default_ua:
        headers["user-agent"] = default_ua
    if protocol.user_agent_template:
        if request.session is None:
            raise ConfigError("missing_session_identity", "Gemini CLI requires a business Session")
        model = header_value(request.model, "model")
        anchor = request.session.model_projection.get_or_bind_model("gemini-cli", model)
        headers["User-Agent"] = protocol.user_agent_template.format(session_model=anchor)
    if profile.user_agent:
        headers["user-agent"] = (
            profile.user_agent.format(client_version=client_version())
            if "{client_version}" in profile.user_agent else profile.user_agent
        )
    for key, value in config.headers.items():
        _set_header(headers, key, value)
    if config.user_agent:
        _set_header(headers, "user-agent", config.user_agent)
    return headers


def _set_header(headers, key, value):
    for existing in tuple(headers):
        if existing.lower() == key.lower() and existing != key:
            del headers[existing]
    headers[key] = value


def project_body(profile, request, payload):
    """Retain early protocol projections; Chat layout runs at the final HTTP boundary."""
    return payload


def selected_profile(config):
    return (config.fingerprint_runtime.profile if config.fingerprint_runtime
            else resolve_profile(config.client_fingerprint, config.protocol))


def uses_attempt_bindings(config) -> bool:
    profile = selected_profile(config)
    entry = profile.for_protocol(config.protocol)
    return any(v in ATTEMPT_BINDINGS for _, v in (*profile.bindings, *entry.bindings))


@dataclass(frozen=True, slots=True)
class PreparedAttempt:
    headers: dict[str, str]
    payload: dict[str, Any]
    body: bytes


def prepare_http_attempt(config, url, headers, payload, *, stream) -> PreparedAttempt:
    """Lower fresh business payload and generate tracing for one physical HTTP exchange."""
    profile = selected_profile(config)
    entry = profile.for_protocol(config.protocol)
    result_headers = dict(headers)
    bindings = [(k, v) for k, v in (*profile.bindings, *entry.bindings)
                if v in ATTEMPT_BINDINGS]
    if bindings:
        values = attempt_bindings()
        for key, source in bindings:
            _set_header(result_headers, key, values[source])
    result_body = payload
    if isinstance(entry.body, ChatBodyPolicy):
        current_request()  # Require the business entrypoint's frozen request context.
        result_body = project_chat_body(entry.body, payload, url=url, provider=config.id,
                                        stream=stream, overrides=config.extra_body)
    elif isinstance(entry.body, ClaudeBodyPolicy):
        validate_claude_overrides(entry.body, config.extra_body)
        request = current_request()
        runtime = config.fingerprint_runtime
        user_id = None
        if entry.body.metadata_user_id:
            from quickquip.llm.client_fingerprints.session_projection import business_session_id

            user_id = json.dumps({
                "device_id": load_claude_device_id(
                    runtime.data_dir if runtime else DATA_DIR,
                    runtime.claude_code_device_id if runtime else "",
                ),
                "account_uuid": "", "session_id": business_session_id(request.session),
            }, separators=(",", ":"))
        result_body = project_claude_body(
            entry.body, payload, user_id=user_id, use_cache=config.prompt_caching,
            cache_ttl=config.cache_ttl, stream=stream,
        )
    elif isinstance(entry.body, GeminiBodyPolicy):
        validate_gemini_overrides(config.extra_body)
        result_body = project_gemini_body(entry.body, payload)
    for key, source in (*profile.bindings, *entry.bindings):
        if source == "retry_count":
            _set_header(result_headers, key, retry_count())
    if entry.beta_rules and not any(k.lower() == "anthropic-beta" for k in config.headers):
        _set_header(result_headers, "anthropic-beta", derive_beta(
            entry.beta_rules, result_body,
            resolve_context_window(config.model_context_windows, str(result_body.get("model", ""))),
        ))
    if entry.body_bindings:
        runtime = config.fingerprint_runtime
        result_body = project_body_bindings(
            entry.body_bindings, current_request(), result_body,
            data_dir=runtime.data_dir if runtime else DATA_DIR, overrides=config.extra_body,
        )
    if stream and (entry.stream_accept == "event-stream"
                   or (not entry.stream_accept and entry.body is None)):
        result_headers = {**result_headers, "accept": "text/event-stream"}
    elif stream and not any(k.lower() == "accept" for k in result_headers):
        result_headers["accept"] = "text/event-stream"
    body = json.dumps(result_body, ensure_ascii=False,
                      separators=(",", ":") if entry.body is not None else None).encode("utf-8")
    return PreparedAttempt(headers=result_headers, payload=result_body, body=body)
