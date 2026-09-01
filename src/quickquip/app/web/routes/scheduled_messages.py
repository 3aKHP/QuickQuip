"""定时消息（群聊 cron 文本消息）的 Web 管理路由。

存储走 ``quickquip.chat.scheduled_messages.ScheduledMessageStore``（无 nonebot 依赖，
本模块不得在顶层 import message_pipeline）；写操作后通过 action_queue 通知 bot 进程
重注册 APScheduler job。
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from quickquip.app.web.action_queue import action_queue
from quickquip.app.web.audit import audit_logger
from quickquip.chat.scheduled_messages import (
    MAX_MESSAGE_LENGTH,
    VALID_KINDS,
    ScheduledMessageStore,
    validate_cron,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_store() -> ScheduledMessageStore:
    """模块级 lazy 工厂：每次请求新建（store 本身每次重读磁盘），方便测试 monkeypatch。"""
    return ScheduledMessageStore()


class ScheduledMessageCreate(BaseModel):
    cron: str = Field(min_length=1)
    group_ids: list[str] = Field(min_length=1)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    enabled: bool = True
    kind: str = "text"  # text 固定文案 | llm LLM 任务指令
    recurring: bool = True  # False 为一次性任务，触发后自动删除


class ScheduledMessageUpdate(BaseModel):
    cron: str | None = None
    group_ids: list[str] | None = None
    message: str | None = Field(default=None, max_length=MAX_MESSAGE_LENGTH)
    enabled: bool | None = None
    kind: str | None = None
    recurring: bool | None = None


def _validate_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind 必须是 {' 或 '.join(VALID_KINDS)}")


def _reload_bot_scheduler() -> None:
    action_queue.enqueue("scheduler_reload", {})


@router.get("/scheduled-messages")
def list_scheduled_messages(group_id: str | None = None):
    jobs = _get_store().list()
    if group_id:
        jobs = [j for j in jobs if group_id in j.group_ids]
    return {"jobs": [j.to_dict() for j in jobs]}


@router.post("/scheduled-messages", status_code=201)
def create_scheduled_message(body: ScheduledMessageCreate, request: Request):
    try:
        validate_cron(body.cron)
        _validate_kind(body.kind)
        job = _get_store().add(
            cron=body.cron,
            group_ids=body.group_ids,
            message=body.message,
            enabled=body.enabled,
            kind=body.kind,
            recurring=body.recurring,
            origin="web",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.warning("scheduled message created via web admin: %s", job.id)
    audit_logger.log(
        request,
        action="create",
        target_type="scheduled_message",
        target_id=job.id,
        summary_after=job.to_dict(),
    )
    _reload_bot_scheduler()
    return job.to_dict()


@router.put("/scheduled-messages/{job_id}")
def update_scheduled_message(job_id: str, body: ScheduledMessageUpdate, request: Request):
    store = _get_store()
    before = store.get(job_id)
    if before is None:
        raise HTTPException(status_code=404, detail="定时消息不存在")
    fields = body.model_dump(exclude_unset=True)
    if "cron" in fields and fields["cron"] is not None:
        try:
            validate_cron(fields["cron"])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if "kind" in fields and fields["kind"] is not None:
        _validate_kind(fields["kind"])
    try:
        before, updated = store.update_for_audit(job_id, **fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if before is None or updated is None:
        raise HTTPException(status_code=404, detail="定时消息不存在")
    if updated is before:
        # 空操作：不产生审计条目，也不触发 bot 端 reload
        return updated.to_dict()
    logger.warning("scheduled message updated via web admin: %s (%s)", job_id, sorted(fields))
    audit_logger.log(
        request,
        action="update",
        target_type="scheduled_message",
        target_id=job_id,
        summary_before=before.to_dict(),
        summary_after=updated.to_dict(),
    )
    _reload_bot_scheduler()
    return updated.to_dict()


@router.delete("/scheduled-messages/{job_id}")
def delete_scheduled_message(job_id: str, request: Request):
    removed = _get_store().remove(job_id)
    if removed is None:
        raise HTTPException(status_code=404, detail="定时消息不存在")
    logger.warning("scheduled message deleted via web admin: %s", job_id)
    audit_logger.log(
        request,
        action="delete",
        target_type="scheduled_message",
        target_id=job_id,
        summary_before=removed.to_dict(),
    )
    _reload_bot_scheduler()
    return {"ok": True}
