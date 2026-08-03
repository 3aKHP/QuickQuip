from __future__ import annotations

import asyncio
from collections import deque
import json
from pathlib import Path
import re
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from quickquip.common.paths import LOGS_DIR
from quickquip.llm.provider import trace_store

router = APIRouter()

_LOGS_DIR = LOGS_DIR
_LOG_FILE_RE = re.compile(r"^quickquip_\d{4}-\d{2}-\d{2}\.log$")
_STREAM_POLL_SECONDS = 1.0
_STREAM_HEARTBEAT_SECONDS = 20.0
_MAX_TAIL_LINES = 500


def _list_log_files() -> list[Path]:
    if not _LOGS_DIR.exists():
        return []
    files = [
        path
        for path in _LOGS_DIR.iterdir()
        if path.is_file() and _LOG_FILE_RE.match(path.name)
    ]
    return sorted(files, key=lambda path: path.name, reverse=True)


def _latest_log_file() -> Path | None:
    files = _list_log_files()
    return files[0] if files else None


def _resolve_log_path(name: str) -> Path:
    if not _LOG_FILE_RE.match(name):
        raise HTTPException(status_code=422, detail="invalid log file name")
    path = _LOGS_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="log file not found")
    return path


def _tail_lines(path: Path, limit: int) -> list[str]:
    buffer: deque[str] = deque(maxlen=max(1, min(limit, _MAX_TAIL_LINES)))
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            buffer.append(raw_line.rstrip("\r\n"))
    return list(buffer)


def _encode_sse_data(payload: str) -> str:
    return "".join(f"data: {line}\n" for line in payload.splitlines() or [""]) + "\n"


def _stream_log_lines(tail: int) -> StreamingResponse:
    def event_stream():
        current_path: Path | None = None
        offset = 0
        sent_initial = False
        last_heartbeat = time.monotonic()

        while True:
            latest = _latest_log_file()
            if latest != current_path:
                current_path = latest
                offset = 0
                sent_initial = False

            if current_path is None or not current_path.exists():
                if time.monotonic() - last_heartbeat >= _STREAM_HEARTBEAT_SECONDS:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.monotonic()
                time.sleep(_STREAM_POLL_SECONDS)
                continue

            if not sent_initial:
                for line in _tail_lines(current_path, tail):
                    yield _encode_sse_data(line)
                try:
                    offset = current_path.stat().st_size
                except OSError:
                    offset = 0
                sent_initial = True
                last_heartbeat = time.monotonic()
                continue

            chunk = ""
            try:
                size = current_path.stat().st_size
                if offset > size:
                    offset = 0
                with current_path.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    chunk = f.read()
                    offset = f.tell()
            except OSError:
                chunk = ""

            if chunk:
                for line in chunk.splitlines():
                    yield _encode_sse_data(line)
                last_heartbeat = time.monotonic()
                continue

            if time.monotonic() - last_heartbeat >= _STREAM_HEARTBEAT_SECONDS:
                yield ": heartbeat\n\n"
                last_heartbeat = time.monotonic()
            time.sleep(_STREAM_POLL_SECONDS)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _encode_trace_sse(entry: dict[str, object]) -> str:
    event_id = int(entry["event_id"])
    payload = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\n{_encode_sse_data(payload)}"


def _stream_trace_calls(request: Request, after_event_id: int | None) -> StreamingResponse:
    async def event_stream():
        cursor = after_event_id
        last_heartbeat = time.monotonic()

        while not await request.is_disconnected():
            events = await asyncio.to_thread(
                trace_store.list_events,
                after_event_id=cursor,
                limit=200,
            )
            if events:
                for event in events:
                    cursor = int(event["event_id"])
                    yield _encode_trace_sse(event)
                last_heartbeat = time.monotonic()
                continue

            if time.monotonic() - last_heartbeat >= _STREAM_HEARTBEAT_SECONDS:
                yield ": heartbeat\n\n"
                last_heartbeat = time.monotonic()
            await asyncio.sleep(_STREAM_POLL_SECONDS)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/logs")
def list_logs():
    files = _list_log_files()
    current_name = files[0].name if files else None
    return {
        "current_file": current_name,
        "files": [
            {
                "name": path.name,
                "size": path.stat().st_size,
                "mtime": int(path.stat().st_mtime),
                "is_current": path.name == current_name,
            }
            for path in files
        ],
    }


@router.get("/logs/files/{name}/tail")
def get_log_tail(name: str, lines: int = Query(default=200, ge=1, le=_MAX_TAIL_LINES)):
    path = _resolve_log_path(name)
    return {
        "name": path.name,
        "lines": _tail_lines(path, lines),
        "size": path.stat().st_size,
        "mtime": int(path.stat().st_mtime),
    }


@router.get("/logs/files/{name}/download")
def download_log_file(name: str):
    path = _resolve_log_path(name)
    return FileResponse(path, media_type="text/plain", filename=path.name)


@router.get("/logs/stream")
def stream_logs(tail: int = Query(default=200, ge=1, le=_MAX_TAIL_LINES)):
    return _stream_log_lines(tail)


@router.get("/logs/trace/stream")
def stream_trace_logs(
    request: Request,
    after_event_id: int | None = Query(default=None, ge=0),
):
    """Stream lightweight Trace index events to the Web Admin client."""

    header_cursor = request.headers.get("last-event-id", "").strip()
    if header_cursor.isdigit():
        after_event_id = max(after_event_id or 0, int(header_cursor))
    return _stream_trace_calls(request, after_event_id)


@router.get("/logs/trace/calls")
def list_trace_calls(
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1),
):
    """List paginated Trace metadata without returning request or response bodies."""

    calls = trace_store.list_calls(limit=limit, before_id=before_id)
    return {
        "calls": calls,
        "next_before_id": int(calls[-1]["id"]) if len(calls) == limit else None,
    }


@router.get("/logs/trace/calls/{call_id}")
def get_trace_call(call_id: str):
    """Load the complete HTTP text payload for one selected Trace call."""

    entry = trace_store.get_call(call_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="trace call not found")
    return entry
