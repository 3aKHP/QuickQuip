from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException

from quickquip.app.web.routes import period_reports  # noqa: E402
from quickquip.chat.period_report import (  # noqa: E402
    PERIOD_MONTHLY,
    PERIOD_WEEKLY,
    PeriodReportStore,
)


@pytest.fixture()
def db(monkeypatch, tmp_path):
    db_path = tmp_path / "period_reports.db"
    monkeypatch.setattr(period_reports, "_DB", db_path)
    return PeriodReportStore(db_path)


def test_list_empty_when_no_db(monkeypatch, tmp_path):
    monkeypatch.setattr(period_reports, "_DB", tmp_path / "missing.db")
    assert period_reports.list_period_reports("10001", "weekly") == []


def test_list_returns_rows_for_group_and_type(db):
    db.upsert("10001", PERIOD_WEEKLY, "2026-W24", "周报A", "m1")
    db.upsert("10001", PERIOD_WEEKLY, "2026-W23", "周报B", "m1")
    db.upsert("10001", PERIOD_MONTHLY, "2026-06", "月报", "m1")
    db.upsert("10002", PERIOD_WEEKLY, "2026-W24", "他群周报", "m1")

    weekly = period_reports.list_period_reports("10001", "weekly")
    assert [r["period_key"] for r in weekly] == ["2026-W24", "2026-W23"]  # DESC
    assert all("content" not in r for r in weekly)  # 列表不返回正文

    # 月报与他群不混入周报查询
    monthly = period_reports.list_period_reports("10001", "monthly")
    assert [r["period_key"] for r in monthly] == ["2026-06"]


def test_list_rejects_invalid_period_type(db):
    with pytest.raises(HTTPException) as exc:
        period_reports.list_period_reports("10001", "quarterly")
    assert exc.value.status_code == 422


def test_list_rejects_invalid_group_id(db):
    with pytest.raises(HTTPException) as exc:
        period_reports.list_period_reports("abc", "weekly")
    assert exc.value.status_code == 422


def test_get_detail_returns_content(db):
    db.upsert("10001", PERIOD_WEEKLY, "2026-W24", "正文内容", "m1")

    row = period_reports.get_period_report("10001", "weekly", "2026-W24")
    assert row["content"] == "正文内容"
    assert row["model_used"] == "m1"


def test_get_detail_404_when_missing(db):
    with pytest.raises(HTTPException) as exc:
        period_reports.get_period_report("10001", "weekly", "2026-W24")
    assert exc.value.status_code == 404


def test_get_text(db):
    db.upsert("10001", PERIOD_MONTHLY, "2026-06", "月报正文", "m1")
    assert period_reports.get_period_report_text("10001", "monthly", "2026-06") == "月报正文"


def test_delete(db, monkeypatch):
    monkeypatch.setattr(period_reports.audit_logger, "log", lambda *a, **k: None)
    db.upsert("10001", PERIOD_WEEKLY, "2026-W24", "x", "m1")
    assert period_reports.delete_period_report("10001", "weekly", "2026-W24", object()) == {"ok": True}
    assert db.get("10001", PERIOD_WEEKLY, "2026-W24") is None


def test_delete_404_when_missing(db):
    with pytest.raises(HTTPException) as exc:
        period_reports.delete_period_report("10001", "weekly", "2026-W24", object())
    assert exc.value.status_code == 404


def test_list_groups_scoped_by_type(db):
    db.upsert("10001", PERIOD_WEEKLY, "2026-W24", "x")
    db.upsert("10002", PERIOD_WEEKLY, "2026-W24", "y")
    db.upsert("10001", PERIOD_MONTHLY, "2026-06", "z")

    assert period_reports.list_period_report_groups("weekly") == ["10001", "10002"]
    assert period_reports.list_period_report_groups("monthly") == ["10001"]


def test_period_key_rejects_garbage(db):
    with pytest.raises(HTTPException) as exc:
        period_reports.get_period_report("10001", "weekly", "garbage")
    assert exc.value.status_code == 422


# ── generation-log ──


@pytest.fixture()
def usage_store_fake(monkeypatch, tmp_path):
    import quickquip.llm.usage_store as usage_store_module
    from quickquip.llm.usage_store import LLMUsageStore

    fake = LLMUsageStore(tmp_path / "u.db")
    monkeypatch.setattr(usage_store_module, "usage_store", fake)
    return fake


def _event(store, *, run_id=None, ts=None, outcome="accepted"):
    store.record({
        "provider_id": "p", "protocol": "openai", "model": "m1",
        "feature": "period_report", "group_id": "10001", "state": "ok",
        "finish_reason": "STOP", "stream": 0, "response_outcome": outcome,
        "cost_usd": 0.01, "duration_ms": 1000.0, "run_id": run_id,
        **({"ts": ts} if ts else {}),
    })


def test_generation_log_run_id_attribution(db, usage_store_fake):
    db.upsert("10001", PERIOD_WEEKLY, "2026-W24", "周报", "m1", run_id="run-w24")
    _event(usage_store_fake, run_id="run-w24", outcome="discarded_empty")
    _event(usage_store_fake, run_id="run-w24")
    _event(usage_store_fake, run_id="run-other")

    result = period_reports.period_report_generation_log("10001", "weekly", "2026-W24")

    assert result["attribution"] == "run_id"
    assert [h["response_outcome"] for h in result["hops"]] == ["discarded_empty", "accepted"]


def test_generation_log_fallback_window_scoped_by_period_type(db, usage_store_fake):
    """prev 查询按同 period_type 取：月报的上一条不是周报。"""
    db.upsert("10001", PERIOD_WEEKLY, "2026-W23", "周报", "m1")  # 无 run_id
    db.upsert("10001", PERIOD_MONTHLY, "2026-05", "五月报", "m1")
    db.upsert("10001", PERIOD_MONTHLY, "2026-06", "六月报", "m1")
    may = db.get("10001", PERIOD_MONTHLY, "2026-05")["generated_at"]
    jun = db.get("10001", PERIOD_MONTHLY, "2026-06")["generated_at"]
    # 五月报 generated_at 之后、六月报 generated_at 当刻：归入六月报
    _event(usage_store_fake, ts=jun)

    result = period_reports.period_report_generation_log("10001", "monthly", "2026-06")

    assert result["attribution"] == "time_window"
    assert len(result["hops"]) == 1
    # 五月报的窗口下界是它自己 6h 封顶（首条月报），而非周报
    assert may < jun


def test_generation_log_404_and_validation(db):
    with pytest.raises(HTTPException) as exc:
        period_reports.period_report_generation_log("10001", "weekly", "2026-W99")
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        period_reports.period_report_generation_log("10001", "weekly", "bad-key")
    assert exc.value.status_code == 422


def test_generation_log_triggers_migration_on_old_schema_db(monkeypatch, tmp_path):
    """旧库（无 run_id 列）经 web 进程直调路由不 500：路由先触发惰性迁移。"""
    import sqlite3

    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE period_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL, period_type TEXT NOT NULL, period_key TEXT NOT NULL,
                generated_at TEXT NOT NULL, published_at TEXT DEFAULT NULL,
                model_used TEXT, char_count INTEGER, content TEXT NOT NULL,
                UNIQUE(group_id, period_type, period_key)
            )
        """)
        conn.execute(
            "INSERT INTO period_reports (group_id, period_type, period_key, generated_at, content) VALUES (?, ?, ?, ?, ?)",
            ("10001", "weekly", "2026-W24", "2026-06-14T06:00:00+00:00", "旧报文"),
        )
    monkeypatch.setattr(period_reports, "_DB", db_path)

    result = period_reports.period_report_generation_log("10001", "weekly", "2026-W24")

    assert result["ok"] is True
    assert result["attribution"] == "time_window"
