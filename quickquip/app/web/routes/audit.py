from fastapi import APIRouter, Query

from quickquip.app.web.audit import audit_logger

router = APIRouter()


@router.get("/audit")
def get_audit_entries(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    operator: str | None = Query(default=None),
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
):
    items, total = audit_logger.query(
        page=page,
        limit=limit,
        action=action,
        target_type=target_type,
        operator=operator,
        since=since,
        until=until,
    )
    return {"items": items, "total": total}
