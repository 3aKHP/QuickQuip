"""LLM request/response tracing infrastructure.

Extracted from the former monolithic ``provider.py``. Provides on-disk
jsonl trace logging (gated by an optional flag file) plus an in-memory
ring buffer for fallback reads.

Tracing is toggleable at runtime: set the ``LLM_TRACE_FLAG_FILE`` env
var to a path; while that file exists, provider clients log full
payloads. The public entry points are :func:`get_trace_entries` /
:func:`clear_trace_entries` (consumed by the Web Admin diagnostics page).

Module-level state (``_TRACE_FLAG_FILE``, ``_TRACE_DIR``,
``_TRACE_LOG_LINES``, ``_LAST_TRACE_CLEANUP_DATE``) is intentionally
kept here rather than in a config object so that
``tests/unit/test_trace_store.py`` can ``monkeypatch.setattr(trace, ...)``
the individual attributes.
"""
from __future__ import annotations

from collections import deque
import datetime
import json
import logging
import os
import time as _time
from pathlib import Path

from quickquip.common.paths import LOGS_DIR

logger = logging.getLogger(__name__)

try:
    from loguru import logger as _loguru_logger
    def _trace_log(msg: str) -> None:
        _loguru_logger.opt(depth=1).info(msg)
except ImportError:
    def _trace_log(msg: str) -> None:  # type: ignore[misc]
        print(msg, flush=True)

# Optional path to a flag file that enables LLM request/response tracing.
# Set via LLM_TRACE_FLAG_FILE env var. When the file exists, full payloads
# and raw responses are logged at DEBUG level.
_TRACE_FLAG_FILE: str = os.getenv("LLM_TRACE_FLAG_FILE", "")
_TRACE_DIR: Path = LOGS_DIR
_TRACE_MEMORY_LIMIT = 200
_TRACE_RETENTION_DAYS = 14
_LAST_TRACE_CLEANUP_DATE: str | None = None


def _trace_active() -> bool:
    return bool(_TRACE_FLAG_FILE and os.path.exists(_TRACE_FLAG_FILE))


_TRACE_LOG_LINES: deque[dict[str, object]] = deque(maxlen=200)


def _daily_trace_path() -> Path:
    return _TRACE_DIR / f"quickquip_trace_{datetime.date.today().isoformat()}.jsonl"


def _cleanup_old_traces() -> None:
    """Remove trace files older than _TRACE_RETENTION_DAYS, throttled to once per day."""
    global _LAST_TRACE_CLEANUP_DATE
    today = datetime.date.today().isoformat()
    if _LAST_TRACE_CLEANUP_DATE == today:
        return
    _LAST_TRACE_CLEANUP_DATE = today

    cutoff = _time.time() - _TRACE_RETENTION_DAYS * 86400
    pattern = "quickquip_trace_????-??-??.jsonl"
    try:
        for p in sorted(_TRACE_DIR.glob(pattern)):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    logger.debug("清理过期 trace 文件：%s", p.name)
            except OSError:
                pass
    except OSError:
        pass


def _record_trace(direction: str, provider_id: str, stream: bool, payload: str) -> None:
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "direction": direction,
        "provider_id": provider_id,
        "stream": stream,
        "payload": payload,
    }
    _TRACE_LOG_LINES.append(entry)
    trace_path = _daily_trace_path()
    try:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.debug("failed to append trace entry to %s", trace_path)
    _cleanup_old_traces()


def _load_trace_entries(limit: int | None = None) -> list[dict[str, object]]:
    if limit is None or limit <= 0:
        limit = _TRACE_MEMORY_LIMIT

    pattern = "quickquip_trace_????-??-??.jsonl"
    items: deque[dict[str, object]] = deque(maxlen=limit)
    files_read = 0
    try:
        for p in sorted(_TRACE_DIR.glob(pattern)):
            try:
                with p.open("r", encoding="utf-8") as f:
                    for raw_line in f:
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(entry, dict):
                            items.append(entry)
                files_read += 1
            except OSError:
                continue
    except OSError:
        pass

    if files_read == 0:
        items = deque(_TRACE_LOG_LINES, maxlen=limit)
    return list(items)


def _count_trace_entries() -> int:
    pattern = "quickquip_trace_????-??-??.jsonl"
    count = 0
    files_read = 0
    try:
        for p in sorted(_TRACE_DIR.glob(pattern)):
            try:
                with p.open("r", encoding="utf-8") as f:
                    for raw_line in f:
                        if raw_line.strip():
                            count += 1
                files_read += 1
            except OSError:
                continue
    except OSError:
        return len(_TRACE_LOG_LINES)
    if files_read == 0:
        return len(_TRACE_LOG_LINES)
    return count


def get_trace_entries(n: int = 50) -> list[dict[str, object]]:
    return _load_trace_entries(n)


def clear_trace_entries() -> int:
    count = _count_trace_entries()
    _TRACE_LOG_LINES.clear()
    pattern = "quickquip_trace_????-??-??.jsonl"
    try:
        _TRACE_DIR.mkdir(parents=True, exist_ok=True)
        for p in sorted(_TRACE_DIR.glob(pattern)):
            try:
                p.write_text("", encoding="utf-8")
            except OSError:
                pass
    except OSError:
        pass
    return count
