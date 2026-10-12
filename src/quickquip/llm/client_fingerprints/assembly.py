"""Pure Profile projection around protocol-owned request construction."""
from __future__ import annotations

import platform
import uuid

from quickquip.common.paths import DATA_DIR
from quickquip.llm.client_fingerprints.catalog import (
    FingerprintRuntime, header_value, resolve_profile, validate_provider_headers,
)
from quickquip.llm.client_fingerprints.identity import client_version, load_install_id
from quickquip.llm.config_errors import ConfigError


def detect_stainless_os() -> str:
    system = platform.system()
    return {"Darwin": "MacOS"}.get(system, system or "Linux")


def assemble_headers(config, request, protocol_headers: dict[str, str]) -> dict[str, str]:
    validate_provider_headers(config.headers)
    runtime = config.fingerprint_runtime or FingerprintRuntime(
        resolve_profile(config.client_fingerprint, config.protocol), "", DATA_DIR,
    )
    profile = runtime.profile
    protocol = profile.for_protocol(config.protocol)
    if runtime.profile.id != config.client_fingerprint:
        raise ConfigError(
            "invalid_profile", "Profile selection does not match its runtime snapshot",
        )
    values = {"stainless_os": detect_stainless_os()}
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
        value = values[source]
        if value:
            headers[key] = header_value(value, key)
    if default_ua:
        headers["user-agent"] = default_ua
    if profile.user_agent:
        headers["user-agent"] = profile.user_agent.format(client_version=client_version())
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
    """Protocol-specific Body adapters can extend this boundary with file-defined policies."""
    return payload
