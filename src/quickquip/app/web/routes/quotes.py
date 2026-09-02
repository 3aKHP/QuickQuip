import logging

from fastapi import APIRouter, HTTPException, Query, Request

from quickquip.chat.group_quotes import GroupQuoteStore, resolve_quote_display_name

router = APIRouter()
logger = logging.getLogger(__name__)


def _sender_identity_sources(group_id: str) -> tuple[dict[str, str] | None, object | None]:
    """取发言人名称解析所需的最新名片表与身份索引，LLM 服务不可用时降级。"""
    from quickquip.app.message_pipeline import stats_tracker

    gs = stats_tracker.get_stats(group_id)
    identity_index = None
    try:
        from quickquip.app.message_pipeline import _ensure_llm_bindings, get_llm_service

        _ensure_llm_bindings()
        identity_index = get_llm_service()._resolve_identities(group_id)
    except Exception:
        logger.debug("语录发言人解析：身份索引不可用，回退快照名", exc_info=True)
    return (gs.user_names if gs else None), identity_index


def _enrich_quote_rows(rows: list[dict], group_id: str) -> list[dict]:
    user_names, identity_index = _sender_identity_sources(group_id)
    for row in rows:
        resolved, changed = resolve_quote_display_name(
            row.get("quoted_user_id", ""), row.get("quoted_sender_name", ""),
            user_names=user_names, identity_index=identity_index,
        )
        row["sender_display"] = resolved
        row["sender_changed"] = changed
    return rows


@router.get("/quotes/groups")
async def list_groups(request: Request):
    from quickquip.app.message_pipeline import group_quote_store

    store: GroupQuoteStore = group_quote_store
    return {"groups": store.groups()}


@router.get("/quotes")
async def list_quotes(
    request: Request,
    group_id: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    keyword: str = Query("", max_length=100),
):
    from quickquip.app.message_pipeline import group_quote_store

    store: GroupQuoteStore = group_quote_store
    rows, total = store.list_quotes(group_id, offset=offset, limit=limit, keyword=keyword)
    rows = _enrich_quote_rows(rows, group_id)
    return {"entries": rows, "total": total, "has_more": offset + limit < total}


@router.get("/quotes/by-seq/{group_id}/{seq}")
async def get_by_seq(group_id: str, seq: int, request: Request):
    from quickquip.app.message_pipeline import group_quote_store

    store: GroupQuoteStore = group_quote_store
    q = store.get_by_seq(group_id, seq)
    if q is None:
        raise HTTPException(404, "quote not found")
    return _enrich_quote_rows([q], group_id)[0]


@router.delete("/quotes/{quote_id}")
async def delete_quote(quote_id: int, request: Request):
    from quickquip.app.message_pipeline import group_quote_store

    store: GroupQuoteStore = group_quote_store
    if not store.delete(quote_id):
        raise HTTPException(404, "quote not found")
    return {"ok": True}
