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
from quickquip.llm.client_fingerprints.identity import client_version, load_install_id
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.client_fingerprints.body_policy import project_chat_body
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
    values = {"stainless_os": detect_stainless_os()}
    sources = {v for _, v in (*profile.bindings, *protocol.bindings)}
    values.update({source: build(request, runtime.data_dir)
                   for source, build in SESSION_BINDINGS.items() if source in sources})
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
        if source in ATTEMPT_BINDINGS:
            continue
        value = values[source]
        if value:
            headers[key] = header_value(value, key)
    if default_ua:
        headers["user-agent"] = default_ua
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
    if entry.body is not None:
        current_request()  # Require the business entrypoint's frozen request context.
        result_body = project_chat_body(entry.body, payload, url=url, provider=config.id,
                                        stream=stream, overrides=config.extra_body)
    if stream and entry.body is None:
        result_headers = {**result_headers, "accept": "text/event-stream"}
    elif stream and not any(k.lower() == "accept" for k in result_headers):
        result_headers["accept"] = "text/event-stream"
    body = json.dumps(result_body, ensure_ascii=False,
                      separators=(",", ":") if entry.body is not None else None).encode("utf-8")
    return PreparedAttempt(headers=result_headers, payload=result_body, body=body)
