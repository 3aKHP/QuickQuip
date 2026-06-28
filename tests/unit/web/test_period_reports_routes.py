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
