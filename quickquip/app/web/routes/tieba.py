import asyncio
import re
import urllib.request

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from quickquip.tieba.service import tieba_service

_ALLOWED_IMAGE_HOST_RE = re.compile(r"^https?://[^/]*\.baidu\.com/")
_IMAGE_PROXY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://tieba.baidu.com/",
}

router = APIRouter()

_FORUM_RE = re.compile(r"^[^\s/\\:]{1,32}$")
_TID_RE = re.compile(r"^\d{1,20}$")
_PREVIEW_MAX_CHARS = 240


def _validate_forum(forum: str) -> str:
    if not _FORUM_RE.match(forum):
        raise HTTPException(status_code=422, detail="invalid forum keyword")
    return forum


def _validate_tid(tid: str) -> str:
    if not _TID_RE.match(tid):
        raise HTTPException(status_code=422, detail="invalid tid")
    return tid


def _preview(text: str) -> str:
    text = text.strip()
    if len(text) <= _PREVIEW_MAX_CHARS:
        return text
    return text[:_PREVIEW_MAX_CHARS] + "…"


@router.get("/tieba/forums")
def list_forums():
    store = tieba_service.store
    forums = []
    for keyword in store.list_forum_keywords():
        state = store.get_forum_state(keyword)
        if state is None:
            continue
        forums.append({
            "forum_keyword": state.forum_keyword,
            "count": len(state.threads),
            "last_sync_started_at": state.last_sync_started_at,
            "last_sync_completed_at": state.last_sync_completed_at,
            "last_sync_status": state.last_sync_status,
            "last_error": state.last_error,
            "login_required": state.login_required,
            "recent_sent_count": len(state.recent_sent_ids),
        })
    return {"forums": forums}


@router.get("/tieba/threads")
def list_threads(
    forum: str = Query(..., max_length=32),
    keyword: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
):
    _validate_forum(forum)
    store = tieba_service.store
    state = store.get_forum_state(forum)
    if state is None:
        return {"threads": [], "total": 0, "has_more": False}

    threads = store.list_threads([forum])
    if keyword:
        kw = keyword.strip().lower()
        threads = [
            t for t in threads
            if kw in t.title.lower() or kw in t.main_post_text.lower() or kw in t.author_name.lower()
        ]
    total = len(threads)
    page = threads[offset:offset + limit]
    return {
        "total": total,
        "has_more": offset + len(page) < total,
        "threads": [
            {
                "tid": t.tid,
                "title": t.title,
                "thread_url": t.thread_url,
                "forum_keyword": t.forum_keyword,
                "author_name": t.author_name,
                "preview": _preview(t.main_post_text),
                "cover_image_url": t.cover_image_url,
                "image_count": len(t.image_urls),
                "fetched_at": t.fetched_at,
                "last_seen_at": t.last_seen_at,
                "is_deleted": t.is_deleted,
                "was_sent": t.tid in state.recent_sent_ids,
            }
            for t in page
        ],
    }


@router.get("/tieba/threads/{forum}/{tid}")
def get_thread(forum: str, tid: str):
    _validate_forum(forum)
    _validate_tid(tid)
    state = tieba_service.store.get_forum_state(forum)
    if state is None:
        raise HTTPException(status_code=404, detail="forum not found")
    thread = state.threads.get(tid)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return {
        **thread.to_dict(),
        "was_sent": tid in state.recent_sent_ids,
    }


@router.get("/tieba/imgproxy")
def proxy_image(url: str = Query(..., max_length=512)):
    if not _ALLOWED_IMAGE_HOST_RE.match(url):
        raise HTTPException(status_code=422, detail="url not allowed")
    try:
        req = urllib.request.Request(url, headers=_IMAGE_PROXY_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            data = resp.read(5 * 1024 * 1024)  # 5 MB cap
    except Exception:
        raise HTTPException(status_code=502, detail="image fetch failed")
    return Response(content=data, media_type=content_type)


@router.get("/tieba/sync")
async def sync_tieba(forum: str | None = Query(default=None, max_length=32)):
    if forum is not None:
        _validate_forum(forum)

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def push(msg: str) -> None:
        queue.put_nowait(msg)

    async def run() -> None:
        try:
            await tieba_service.sync_now(force=True, forum_keyword=forum, on_progress=push)
        except Exception as exc:
            push(f"✗ 同步失败：{exc}")
        finally:
            queue.put_nowait(None)

    asyncio.create_task(run())

    async def event_stream():
        while True:
            msg = await queue.get()
            if msg is None:
                yield "data: [done]\n\n"
                break
            yield f"data: {msg}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
