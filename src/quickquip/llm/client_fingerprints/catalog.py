"""Validate TOML profiles and retain one immutable catalog per process/directory."""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
import re
from string import Formatter
import tomllib

from quickquip.common.paths import CONFIG_DIR
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.client_fingerprints.body_policy import ChatBodyPolicy, parse_body_policy
from quickquip.llm.client_fingerprints.body_bindings import BodyBindings, parse_body_bindings
from quickquip.llm.client_fingerprints.claude_policy import (
    BetaRule, ClaudeBodyPolicy, parse_beta_rules, parse_claude_policy,
)
from quickquip.llm.client_fingerprints.gemini_policy import GeminiBodyPolicy, parse_gemini_policy
from quickquip.llm.client_fingerprints.session_projection import SESSION_BINDINGS
from quickquip.llm.client_fingerprints.trace_context import ATTEMPT_BINDINGS

PROTOCOLS = ("openai", "claude", "gemini", "openai_responses")
QUICKQUIP_BINDINGS = {
    "x-quickquip-install": "install_id",
    "x-quickquip-session": "epoch_id",
    "x-quickquip-cluster": "cluster_id",
    "x-quickquip-client": "client_version",
}
_HEADER = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_.-]*\Z")


@dataclass(frozen=True, slots=True)
class ProtocolFingerprint:
    headers: tuple[tuple[str, str], ...] = ()
    bindings: tuple[tuple[str, str], ...] = ()
    body: ChatBodyPolicy | ClaudeBodyPolicy | GeminiBodyPolicy | None = None
    header_order: tuple[str, ...] = ()
    body_bindings: BodyBindings = ()
    beta_rules: tuple[BetaRule, ...] = ()
    stream_accept: str = ""
    protocol_ref: str = ""
    user_agent_template: str = ""
    api_key_transport: str = "query"


@dataclass(frozen=True, slots=True)
class ClientFingerprintProfile:
    id: str
    label: str
    user_agent: str
    headers: tuple[tuple[str, str], ...]
    bindings: tuple[tuple[str, str], ...]
    protocols: tuple[tuple[str, ProtocolFingerprint], ...]

    def for_protocol(self, protocol: str) -> ProtocolFingerprint:
        for name, fingerprint in self.protocols:
            if name == protocol:
                return fingerprint
        raise ConfigError("invalid_profile", "Profile does not support this protocol")


@dataclass(frozen=True, slots=True)
class FingerprintRuntime:
    profile: ClientFingerprintProfile
    cluster: str
    data_dir: Path
    claude_code_device_id: str = ""
    gemini_cli_install_id: str = ""


def header_value(value: str, location: str) -> str:
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ConfigError("invalid_field", "Header value must be printable ASCII", location)
    return value


def validate_provider_headers(
    headers: dict[str, str], location="headers", *, profile=None, protocol=None,
) -> None:
    protected = set(QUICKQUIP_BINDINGS)
    if profile is not None:
        entry = profile.for_protocol(protocol)
        protected.update(k.lower() for k, v in (*profile.bindings, *entry.bindings)
                         if v in (*SESSION_BINDINGS, *ATTEMPT_BINDINGS, "gemini_cli_install_id"))
        if protocol == "gemini" and entry.api_key_transport == "header":
            protected.add("x-goog-api-key")
    for name in headers:
        if name.lower() in protected:
            raise ConfigError(
                "profile_owned_header", "Dynamic headers are managed by the selected Profile",
                f"{location}.{name}",
            )


def _table(raw, allowed, location):
    if not isinstance(raw, dict) or set(raw) - set(allowed):
        raise ConfigError("invalid_profile", "Invalid Profile fields", location)
    return raw


def _headers(raw, profile_id, location, *, bindings=False):
    _table(raw, raw.keys() if isinstance(raw, dict) else (), location)
    output = []
    seen = set()
    for name, value in raw.items():
        if not _HEADER.fullmatch(name) or name.lower() in seen:
            raise ConfigError("invalid_profile", "Invalid or duplicate header", location)
        key = name.lower()
        seen.add(key)
        if key in ("authorization", "x-api-key", "x-goog-api-key", "content-type"):
            raise ConfigError("invalid_profile", "Protocol headers are adapter-owned", location)
        header_value(value, location)
        if key in QUICKQUIP_BINDINGS:
            if profile_id != "quickquip" or not bindings or value != QUICKQUIP_BINDINGS[key]:
                raise ConfigError("invalid_profile", "Invalid QuickQuip header ownership", location)
        if bindings and value not in (*QUICKQUIP_BINDINGS.values(), "stainless_os",
                                      "timeout_seconds", "retry_count",
                                      "gemini_cli_install_id",
                                      *SESSION_BINDINGS, *ATTEMPT_BINDINGS):
            raise ConfigError("invalid_profile", "Unknown dynamic binding", location)
        if bindings and value in QUICKQUIP_BINDINGS.values() and profile_id != "quickquip":
            raise ConfigError("invalid_profile", "QuickQuip identity is Profile-owned", location)
        output.append((name, value))
    return tuple(output)


def parse_profile(content: str, expected_id: str) -> ClientFingerprintProfile:
    location = f"client_profiles.{expected_id}"
    try:
        raw = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("invalid_profile", f"Invalid Profile TOML: {exc}", location) from None
    _table(raw, ("format_version", "id", "label", "user_agent", "headers", "bindings",
                 "protocols"), location)
    if type(raw.get("format_version")) is not int or raw["format_version"] != 1:
        raise ConfigError("invalid_profile", "Unsupported Profile format", location)
    ident = raw.get("id")
    if not isinstance(ident, str) or not _IDENTIFIER.fullmatch(ident) or ident != expected_id:
        raise ConfigError("invalid_profile", "Profile ID must match its filename", location)
    label = raw.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ConfigError("invalid_profile", "Profile label is required", location)
    ua = header_value(raw.get("user_agent", ""), location)
    try:
        for _, field, spec, conversion in Formatter().parse(ua):
            if field is not None and (field != "client_version" or spec or conversion):
                raise ValueError("unsupported substitution")
    except ValueError:
        raise ConfigError("invalid_profile", "Invalid User-Agent template", location) from None
    protocols = _table(raw.get("protocols", {}), PROTOCOLS, location)
    if not protocols:
        raise ConfigError("invalid_profile", "Profile requires supported protocols", location)
    headers = _headers(raw.get("headers", {}), ident, location)
    bindings = _headers(raw.get("bindings", {}), ident, location, bindings=True)
    if ident == "quickquip" and dict((k.lower(), v) for k, v in bindings) != QUICKQUIP_BINDINGS:
        raise ConfigError("invalid_profile", "QuickQuip requires its four bindings", location)
    entries = []
    for protocol, entry in protocols.items():
        _table(entry, ("headers", "bindings", "body", "header_order", "body_bindings",
                       "beta_rules", "stream_accept", "protocol_ref", "user_agent_template",
                       "api_key_transport"), location)
        ref = entry.get("protocol_ref", "")
        if (not isinstance(ref, str) or (ref and (not _IDENTIFIER.fullmatch(ref)
                or ref == ident or set(entry) != {"protocol_ref"}))):
            raise ConfigError("invalid_profile", "Invalid protocol reference", location)
        static = _headers(entry.get("headers", {}), ident, location)
        dynamic = _headers(entry.get("bindings", {}), ident, location, bindings=True)
        names = [k.lower() for k, _ in (*headers, *bindings, *static, *dynamic)]
        if len(names) != len(set(names)):
            raise ConfigError("invalid_profile", "Duplicate Profile header", location)
        body = None
        if "body" in entry:
            if protocol == "claude":
                body = parse_claude_policy(entry["body"], location)
            elif protocol == "gemini":
                body = parse_gemini_policy(entry["body"], location)
            else:
                body = parse_body_policy(entry["body"], protocol, location)
        body_bindings = (parse_body_bindings(entry["body_bindings"], protocol, location)
                         if "body_bindings" in entry else ())
        order = entry.get("header_order", [])
        if (not isinstance(order, list)
                or any(not isinstance(k, str) or not _HEADER.fullmatch(k) for k in order)
                or len({k.lower() for k in order}) != len(order)):
            raise ConfigError("invalid_profile", "Invalid Header order", location)
        beta_rules = (parse_beta_rules(entry["beta_rules"], protocol, location)
                      if "beta_rules" in entry else ())
        stream_accept = entry.get("stream_accept", "")
        if stream_accept not in ("", "preserve", "event-stream"):
            raise ConfigError("invalid_profile", "Invalid streaming Accept policy", location)
        ua_template = header_value(entry.get("user_agent_template", ""), location)
        if ua_template:
            try:
                if protocol != "gemini" or any(
                    field is not None and (field != "session_model" or spec or conversion)
                    for _, field, spec, conversion in Formatter().parse(ua_template)
                ):
                    raise ValueError("unsupported template")
            except ValueError:
                raise ConfigError("invalid_profile", "Invalid Gemini UA template",
                                  location) from None
            if any(k.lower() == "user-agent" for k, _ in (*headers, *static, *bindings, *dynamic)):
                raise ConfigError("invalid_profile", "Duplicate Profile UA", location)
        transport = entry.get("api_key_transport", "query")
        if transport not in ("query", "header") or ("api_key_transport" in entry
                                                   and protocol != "gemini"):
            raise ConfigError("invalid_profile", "Invalid Gemini API Key transport", location)
        if any(v == "gemini_cli_install_id" for _, v in (*bindings, *dynamic)):
            if protocol != "gemini":
                raise ConfigError("invalid_profile", "Gemini identity requires Gemini", location)
        if isinstance(body, ClaudeBodyPolicy) and body.metadata_user_id:
            if dict((k.lower(), v) for k, v in (*bindings, *dynamic)).get(
                "x-claude-code-session-id"
            ) != "business_session_id":
                raise ConfigError("invalid_profile", "CC metadata requires its Session binding",
                                  location)
        entries.append((protocol, ProtocolFingerprint(
            headers=static, bindings=dynamic, body=body, header_order=tuple(order),
            body_bindings=body_bindings, beta_rules=beta_rules, stream_accept=stream_accept,
            protocol_ref=ref,
            user_agent_template=ua_template, api_key_transport=transport,
        )))
    return ClientFingerprintProfile(ident, label, ua, headers, bindings, tuple(entries))


def get_catalog(config_dir: Path | None = None) -> tuple[ClientFingerprintProfile, ...]:
    """All call shapes share one canonical startup snapshot per configuration root."""
    return _load_catalog((Path(config_dir) if config_dir is not None else CONFIG_DIR).resolve())


@lru_cache(maxsize=None)
def _load_catalog(config_dir: Path) -> tuple[ClientFingerprintProfile, ...]:
    bundled = files(__package__).joinpath("defaults")
    contents = {p.name[:-5]: p.read_text(encoding="utf-8")
                for p in bundled.iterdir() if p.name.endswith(".toml")}
    directory = Path(config_dir) / "client_profiles"
    try:
        if directory.exists():
            for path in sorted(directory.glob("*.toml")):
                if not _IDENTIFIER.fullmatch(path.stem):
                    raise ConfigError("invalid_profile", "Invalid Profile filename")
                contents[path.stem] = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigError("invalid_profile", "Cannot read Profile files") from exc
    parsed = {ident: parse_profile(contents[ident], ident) for ident in sorted(contents)}
    result = []
    for profile in parsed.values():
        entries = []
        for protocol, entry in profile.protocols:
            if entry.protocol_ref:
                target = parsed.get(entry.protocol_ref)
                if target is None or target.headers or target.bindings or target.user_agent:
                    raise ConfigError("invalid_profile",
                                      "Reference requires a protocol-local target")
                entry = target.for_protocol(protocol)
                if entry.protocol_ref:
                    raise ConfigError("invalid_profile",
                                      "Chained protocol references are unsupported")
            names = [k.lower() for k, _ in
                     (*profile.headers, *profile.bindings, *entry.headers, *entry.bindings)]
            if len(set(names)) != len(names):
                raise ConfigError("invalid_profile", "Duplicate referenced Header")
            entries.append((protocol, entry))
        result.append(replace(profile, protocols=tuple(entries)))
    return tuple(result)


def resolve_profile(ident: str, protocol: str, config_dir: Path = CONFIG_DIR):
    for profile in get_catalog(config_dir):
        if profile.id == ident:
            profile.for_protocol(protocol)
            return profile
    raise ConfigError("invalid_profile", "Unknown client fingerprint Profile",
                      "client_fingerprint", {"id": ident})


def profile_metadata(config_dir: Path = CONFIG_DIR) -> list[dict]:
    return [{"id": p.id, "label": p.label, "protocols": [n for n, _ in p.protocols]}
            for p in get_catalog(config_dir)]
