"""Validate TOML profiles and retain one immutable catalog per process/directory."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
import re
from string import Formatter
import tomllib

from quickquip.common.paths import CONFIG_DIR
from quickquip.llm.config_errors import ConfigError

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


def header_value(value: str, location: str) -> str:
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise ConfigError("invalid_field", "Header value must be printable ASCII", location)
    return value


def validate_provider_headers(headers: dict[str, str], location="headers") -> None:
    for name in headers:
        if name.lower() in QUICKQUIP_BINDINGS:
            raise ConfigError(
                "profile_owned_header", "QuickQuip headers are managed by its Profile",
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
        if key in ("authorization", "x-api-key", "content-type"):
            raise ConfigError("invalid_profile", "Protocol headers are adapter-owned", location)
        header_value(value, location)
        if key in QUICKQUIP_BINDINGS:
            if profile_id != "quickquip" or not bindings or value != QUICKQUIP_BINDINGS[key]:
                raise ConfigError("invalid_profile", "Invalid QuickQuip header ownership", location)
        if bindings and value not in (*QUICKQUIP_BINDINGS.values(), "stainless_os"):
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
        _table(entry, ("headers", "bindings"), location)
        static = _headers(entry.get("headers", {}), ident, location)
        dynamic = _headers(entry.get("bindings", {}), ident, location, bindings=True)
        names = [k.lower() for k, _ in (*headers, *bindings, *static, *dynamic)]
        if len(names) != len(set(names)):
            raise ConfigError("invalid_profile", "Duplicate Profile header", location)
        entries.append((protocol, ProtocolFingerprint(static, dynamic)))
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
    return tuple(parse_profile(contents[ident], ident) for ident in sorted(contents))


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
