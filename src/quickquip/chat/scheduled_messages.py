"""群聊定时消息任务的 JSON 持久化与校验。

存储不变量与 ``quickquip.common.opt_in_groups`` 一致：
FileLock 互斥、锁内重读合并、tmp+replace 原子落盘——bot 进程（命令 / LLM 工具路径）
与 Web Admin 进程交叉写入不丢更新。

本模块不得 import nonebot 或 message_pipeline：Web Admin 进程也直接使用本模块。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from filelock import FileLock

from quickquip.common.opt_in_groups import normalize_digit_group_id
from quickquip.common.paths import SCHEDULED_MESSAGES_JSON_PATH

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 500
VALID_ORIGINS = ("command", "llm", "web")
VALID_KINDS = ("text", "llm")

_CRON_FIELD_RE = re.compile(r"^[\d*,/\-]+$")


def validate_cron(cron_expr: str) -> None:
    """校验 5 段式 cron 表达式，非法时抛 ValueError。

    优先用 APScheduler 的 CronTrigger 做真实校验（apscheduler 不依赖 nonebot
    运行态，Web Admin 进程可安全 import）；不可用时退化为字段数与字符集检查。
    """
    expr = (cron_expr or "").strip()
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron 表达式必须是 5 段（分 时 日 月 周）：{cron_expr!r}")
    try:
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        for part in parts:
            if not _CRON_FIELD_RE.match(part):
                raise ValueError(f"cron 字段含非法字符：{part!r}")
        return
    try:
        CronTrigger.from_crontab(expr)
    except (ValueError, KeyError) as exc:
        raise ValueError(f"非法 cron 表达式 {cron_expr!r}: {exc}") from exc


def normalize_group_ids(group_ids: Any) -> list[str]:
    """归一化群号列表：去重、保持顺序、全数字校验。空列表抛 ValueError。"""
    if not isinstance(group_ids, (list, tuple)):
        raise ValueError("group_ids 必须是群号列表")
    result: list[str] = []
    for raw in group_ids:
        gid = normalize_digit_group_id(raw)
        if gid not in result:
            result.append(gid)
    if not result:
        raise ValueError("group_ids 不能为空")
    return result


def validate_message(message: Any) -> str:
    text = str(message or "").strip()
    if not text:
        raise ValueError("消息内容不能为空")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"消息内容过长（>{MAX_MESSAGE_LENGTH} 字符）")
    return text


@dataclass
class ScheduledMessage:
    id: str
    cron: str
    group_ids: list[str]
    message: str
    enabled: bool = True
    # text：message 为到点原样发送的固定文案；
    # llm：message 为喂给 LLM 的任务指令（prompt），生成结果发群。
    kind: str = "text"
    # recurring=False 为一次性任务：触发一次后自动删除。
    recurring: bool = True
    origin: str = "web"  # command | llm | web
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduledMessage":
        """容错反序列化：缺字段用默认值，坏条目抛 ValueError 由调用方跳过。"""
        if not isinstance(data, dict):
            raise ValueError("entry must be a dict")
        job_id = str(data.get("id") or "").strip()
        if not job_id:
            raise ValueError("entry missing id")
        cron = str(data.get("cron") or "").strip()
        validate_cron(cron)
        group_ids = normalize_group_ids(data.get("group_ids"))
        message = validate_message(data.get("message"))
        kind = str(data.get("kind") or "text")
        if kind not in VALID_KINDS:
            kind = "text"
        origin = str(data.get("origin") or "web")
        if origin not in VALID_ORIGINS:
            origin = "web"
        return cls(
            id=job_id,
            cron=cron,
            group_ids=group_ids,
            message=message,
            enabled=bool(data.get("enabled", True)),
            kind=kind,
            recurring=bool(data.get("recurring", True)),
            origin=origin,
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


class ScheduledMessageStore:
    """``{"jobs": [...]}`` JSON 持久化的定时消息任务存储。

    读操作每次重读磁盘（文件极小，换取跨进程实时一致）；
    写操作在 FileLock 内重读-合并-原子落盘。
    """

    def __init__(self, path: str | Path = SCHEDULED_MESSAGES_JSON_PATH) -> None:
        self.path = Path(path)

    def _lock(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self.path) + ".lock")

    def _load_unlocked(self) -> list[ScheduledMessage]:
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            logger.warning("scheduled_messages: bad JSON in %s, treating as empty", self.path)
            return []
        jobs: list[ScheduledMessage] = []
        for raw in data.get("jobs", []):
            try:
                jobs.append(ScheduledMessage.from_dict(raw))
            except ValueError:
                logger.warning("scheduled_messages: skipping invalid entry: %r", raw)
        return jobs

    def _save_unlocked(self, jobs: list[ScheduledMessage]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(
                    {"jobs": [j.to_dict() for j in jobs]},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            tmp.replace(self.path)
        except OSError:
            logger.warning("scheduled_messages: failed to save to %s", self.path, exc_info=True)
            tmp.unlink(missing_ok=True)
            raise

    # ── Read ─────────────────────────────────────────────────────────────

    def list(self) -> list[ScheduledMessage]:
        return self._load_unlocked()

    def get(self, job_id: str) -> ScheduledMessage | None:
        for job in self._load_unlocked():
            if job.id == job_id:
                return job
        return None

    # ── Write ────────────────────────────────────────────────────────────

    def add(
        self,
        *,
        cron: str,
        group_ids: list[str],
        message: str,
        enabled: bool = True,
        kind: str = "text",
        recurring: bool = True,
        origin: str = "web",
    ) -> ScheduledMessage:
        validate_cron(cron)
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock():
            jobs = self._load_unlocked()
            existing = {j.id for j in jobs}
            job_id = f"sm_{uuid.uuid4().hex[:8]}"
            while job_id in existing:
                job_id = f"sm_{uuid.uuid4().hex[:8]}"
            job = ScheduledMessage(
                id=job_id,
                cron=cron.strip(),
                group_ids=normalize_group_ids(group_ids),
                message=validate_message(message),
                enabled=bool(enabled),
                kind=kind if kind in VALID_KINDS else "text",
                recurring=bool(recurring),
                origin=origin if origin in VALID_ORIGINS else "web",
                created_at=now,
                updated_at=now,
            )
            jobs.append(job)
            self._save_unlocked(jobs)
        return job

    def update(self, job_id: str, **fields: Any) -> ScheduledMessage | None:
        """更新指定字段（cron/group_ids/message/enabled/kind/recurring），返回更新后的任务；不存在返回 None。"""
        allowed = {"cron", "group_ids", "message", "enabled", "kind", "recurring"}
        with self._lock():
            jobs = self._load_unlocked()
            for i, job in enumerate(jobs):
                if job.id != job_id:
                    continue
                data = job.to_dict()
                for key, value in fields.items():
                    if key in allowed and value is not None:
                        data[key] = value
                data["updated_at"] = datetime.now().isoformat(timespec="seconds")
                updated = ScheduledMessage.from_dict(data)
                jobs[i] = updated
                self._save_unlocked(jobs)
                return updated
        return None

    def set_enabled(self, job_id: str, enabled: bool) -> ScheduledMessage | None:
        return self.update(job_id, enabled=enabled)

    def remove(self, job_id: str) -> ScheduledMessage | None:
        with self._lock():
            jobs = self._load_unlocked()
            for i, job in enumerate(jobs):
                if job.id == job_id:
                    removed = jobs.pop(i)
                    self._save_unlocked(jobs)
                    return removed
        return None
