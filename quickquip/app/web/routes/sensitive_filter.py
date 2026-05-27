"""Read-only sensitive-word filter status endpoint.

Exposes load state and aggregate counts for the operator dashboard. The
endpoint deliberately does NOT expose:

- The matched words themselves (plaintext or hash form)
- Per-category breakdown beyond aggregate block/soft totals
- Hit logs or recent matches
- The sensitive TOML file path

Hit-level visibility lives in the regular log stream (logger
``quickquip.common.sensitive_filter``); this endpoint is purely a "is the
tripwire armed and how many tripwires are set" health check.

The web admin process is separate from the bot process, so this route
loads its own ``SensitiveFilter`` instance from the shared TOML file.
The numbers stay consistent with what the bot sees as long as both
read the same file.
"""
from __future__ import annotations

from fastapi import APIRouter

from quickquip.common.paths import CONFIG_SENSITIVE_WORDS_TOML
from quickquip.common.sensitive_filter import SensitiveFilter

router = APIRouter()


@router.get("/sensitive-filter/status")
def get_sensitive_filter_status() -> dict:
    sf = SensitiveFilter.from_toml(CONFIG_SENSITIVE_WORDS_TOML)
    config_exists = CONFIG_SENSITIVE_WORDS_TOML.exists()
    stats = sf.stats if sf.is_loaded else {"total": 0, "block": 0, "soft": 0}
    return {
        "loaded": sf.is_loaded,
        "config_exists": config_exists,
        "stats": stats,
    }
