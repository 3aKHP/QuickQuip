import logging

from fastapi import APIRouter, HTTPException, Query, Request

from quickquip.chat.group_quotes import GroupQuoteStore, attach_sender_display

router = APIRouter()
logger = logging.getLogger(__name__)


def _enrich_quote_rows(rows: list[dict], group_id: str) -> list[dict]:
    from quickquip.app.message_pipeline import get_sender_identity_sources

    user_names, identity_index = get_sender_identity_sources(group_id)
    return attach_sender_display(rows, user_names=user_names, identity_index=identity_index)


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
