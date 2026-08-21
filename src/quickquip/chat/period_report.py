"""群周报 / 群月报存储与采样。

周报/月报数据源复用 wordcloud collector（always-on，不删除），按天采样后传给
LLM 生成管线（llm/summarize.py: generate_period_report）。

- PeriodReportStore：SQLite 存储，按 (group_id, period_type, period_key) 唯一。
- PeriodReportEnabledGroups：周/月各自独立的 opt-in 群集合。
- sample_messages_by_day：按天均匀采样，控制喂给 LLM 的总量。
- period_key_for：生成 ISO 周号（2026-W24）或年月（2026-06）。
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.common.opt_in_groups import OptInGroupSet
from quickquip.common.paths import PERIOD_REPORTS_DB_PATH

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)

# period_type 取值
PERIOD_WEEKLY = "weekly"
PERIOD_MONTHLY = "monthly"
_VALID_PERIOD_TYPES = {PERIOD_WEEKLY, PERIOD_MONTHLY}


def period_key_for(period_type: str, ref_date: date) -> str:
    """生成 period 标识：周报为 ISO 周号（2026-W24），月报为年月（2026-06）。

    ref_date 通常为"上一个完整周期里的任意一天"（如周一凌晨生成的周报，ref_date 取上周内某天）。
    """
    if period_type == PERIOD_WEEKLY:
        iso_year, iso_week, _ = ref_date.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if period_type == PERIOD_MONTHLY:
        return f"{ref_date.year:04d}-{ref_date.month:02d}"
    raise ValueError(f"未知 period_type: {period_type!r}")


def period_label_for(period_type: str, period_key: str) -> str:
    """人类可读的周期标签（用于 LLM prompt）。"""
    if period_type == PERIOD_WEEKLY:
        # period_key 形如 2026-W24，解析出 ISO 年和周号
        iso_year, week_num = period_key.split("-W")
        return f"{iso_year} 年第 {int(week_num)} 周"
    if period_type == PERIOD_MONTHLY:
        year, month = period_key.split("-")
        return f"{year} 年 {int(month)} 月"
    return period_key


def sample_messages_by_day(
    messages: list[dict],
    per_day: int,
) -> list[dict]:
    """按本地日期分组，每组均匀抽取至多 per_day 条，合并后按时间戳排序。

    保证覆盖全周期（每天都被采到），同时控制总量。采用等距抽样（确定性，不依赖随机种子）。
    """
    if per_day <= 0 or not messages:
        return []

    by_day: dict[date, list[dict]] = defaultdict(list)
    for entry in messages:
        ts = float(entry.get("ts", 0))
        day = datetime.fromtimestamp(ts, tz=_LOCAL_TZ).date()
        by_day[day].append(entry)

    sampled: list[dict] = []
    for day in sorted(by_day.keys()):
        bucket = by_day[day]
        if len(bucket) <= per_day:
            sampled.extend(bucket)
        else:
            # 均匀抽取：按时间戳排序后等距取 per_day 个
            bucket.sort(key=lambda x: float(x.get("ts", 0)))
            step = len(bucket) / per_day
            indices = [int(i * step) for i in range(per_day)]
            sampled.extend(bucket[i] for i in indices)

    sampled.sort(key=lambda x: float(x.get("ts", 0)))
    return sampled


class PeriodReportStore:
    """SQLite store for weekly/monthly group reports.

    唯一键 (group_id, period_type, period_key)：同一群同一周期只保留最新一篇。
    """

    def __init__(self, db_path: str | Path = PERIOD_REPORTS_DB_PATH):
        self.db_path = Path(db_path)
        self._unavailable = False
        try:
            self._init_db()
        except sqlite3.Error as exc:
            logger.error("PeriodReportStore 数据库初始化失败 (%s)：%s", self.db_path, exc)
            self._unavailable = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS period_reports (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id     TEXT NOT NULL,
                    period_type  TEXT NOT NULL,
                    period_key   TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    published_at TEXT DEFAULT NULL,
                    model_used   TEXT,
                    char_count   INTEGER,
                    content      TEXT NOT NULL,
                    UNIQUE(group_id, period_type, period_key)
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def upsert(
        self,
        group_id: int | str,
        period_type: str,
        period_key: str,
        content: str,
        model_used: str | None = None,
    ) -> None:
        if self._unavailable:
            raise RuntimeError("周期报告数据库不可用")
        if period_type not in _VALID_PERIOD_TYPES:
            raise ValueError(f"未知 period_type: {period_type!r}")
        generated_at = datetime.now(tz=timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO period_reports
                    (group_id, period_type, period_key, generated_at, model_used, char_count, content)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(group_id, period_type, period_key) DO UPDATE SET
                    generated_at = excluded.generated_at,
                    model_used   = excluded.model_used,
                    char_count   = excluded.char_count,
                    content      = excluded.content,
                    published_at = NULL
                """,
                (str(group_id), period_type, period_key, generated_at, model_used, len(content), content),
            )
            conn.commit()
        finally:
            conn.close()

    def get(self, group_id: int | str, period_type: str, period_key: str) -> dict | None:
        if self._unavailable:
            raise RuntimeError("周期报告数据库不可用")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM period_reports WHERE group_id = ? AND period_type = ? AND period_key = ?",
                (str(group_id), period_type, period_key),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_unpublished(self, period_type: str) -> list[dict]:
        """返回指定 period_type 下所有未发布的报告。"""
        if self._unavailable:
            raise RuntimeError("周期报告数据库不可用")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM period_reports WHERE period_type = ? AND published_at IS NULL "
                "ORDER BY period_key, group_id",
                (period_type,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_published(self, group_id: int | str, period_type: str, period_key: str) -> None:
        if self._unavailable:
            raise RuntimeError("周期报告数据库不可用")
        published_at = datetime.now(tz=timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE period_reports SET published_at = ? "
                "WHERE group_id = ? AND period_type = ? AND period_key = ?",
                (published_at, str(group_id), period_type, period_key),
            )
            conn.commit()
        finally:
            conn.close()


class PeriodReportEnabledGroups(OptInGroupSet):
    """管理某个 period_type（weekly/monthly）的 opt-in 群集合（默认关闭）。"""

    def __init__(self, period_type: str, path: str | Path):
        if period_type not in _VALID_PERIOD_TYPES:
            raise ValueError(f"未知 period_type: {period_type!r}")
        self.period_type = period_type
        self.log_label = f"period_report[{period_type}]"
        super().__init__(path)


def compute_period_window(period_type: str, now: datetime) -> tuple[float, float, str, str]:
    """计算"上一个完整周期"的 [start_ts, end_ts) 窗口及对应的 period_key/label。

    - 周报：now 所在周的前一周（周一 00:00 到下周一 00:00）。
    - 月报：now 所在月的前一整月（1 日 00:00 到次月 1 日 00:00）。
    """
    if period_type == PERIOD_WEEKLY:
        # 本周一
        this_week_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        start = this_week_monday - timedelta(weeks=1)
        end = this_week_monday
        ref_date = start.date()  # 上周内任意一天都映射到同一 ISO 周
        key = period_key_for(period_type, ref_date)
        label = period_label_for(period_type, key)
        return start.timestamp(), end.timestamp(), key, label

    if period_type == PERIOD_MONTHLY:
        # 本月 1 日
        this_month_first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start = (this_month_first - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = this_month_first
        ref_date = start.date()
        key = period_key_for(period_type, ref_date)
        label = period_label_for(period_type, key)
        return start.timestamp(), end.timestamp(), key, label

    raise ValueError(f"未知 period_type: {period_type!r}")
