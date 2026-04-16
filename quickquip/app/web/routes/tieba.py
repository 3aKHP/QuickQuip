import re

from fastapi import APIRouter, HTTPException, Query

from quickquip.tieba.service import tieba_service

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
