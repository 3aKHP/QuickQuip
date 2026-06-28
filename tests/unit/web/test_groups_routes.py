from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException

import quickquip.app.message_pipeline as message_pipeline  # noqa: E402
from quickquip.app.web.routes import groups  # noqa: E402


class FakeEnabledGroups:
    def __init__(self):
        self._set: set[str] = set()

    def add(self, gid):
        self._set.add(str(gid))

    def remove(self, gid):
        self._set.discard(str(gid))

    def contains(self, gid):
        return str(gid) in self._set

    def all_groups(self):
        return sorted(self._set)


def _patch_audit_noop(monkeypatch):
    monkeypatch.setattr(groups.audit_logger, "log", lambda *a, **k: None)


def test_set_weekly_group_enables(monkeypatch):
    fake = FakeEnabledGroups()
    monkeypatch.setattr(message_pipeline, "weekly_enabled_groups", fake)
    _patch_audit_noop(monkeypatch)

    assert groups.set_weekly_group("10001", groups.GroupToggle(enabled=True), object()) == {"ok": True}
    assert fake.contains("10001")


def test_set_monthly_group_disables(monkeypatch):
    fake = FakeEnabledGroups()
    fake.add("10002")
    monkeypatch.setattr(message_pipeline, "monthly_enabled_groups", fake)
    _patch_audit_noop(monkeypatch)

    groups.set_monthly_group("10002", groups.GroupToggle(enabled=False), object())
    assert not fake.contains("10002")


def test_run_weekly_now_enqueues_period_report(monkeypatch):
    fake = FakeEnabledGroups()
    fake.add("10001")
    monkeypatch.setattr(message_pipeline, "weekly_enabled_groups", fake)
    captured: list[tuple] = []
    monkeypatch.setattr(
        groups.action_queue,
        "enqueue",
        lambda action_type, payload=None: captured.append((action_type, payload)) or {"id": "a1"},
    )
    _patch_audit_noop(monkeypatch)

    result = groups.run_weekly_now("10001", object())
    assert result["queued"] is True
    assert captured == [("period_report_now", {"group_id": "10001", "period_type": "weekly"})]


def test_run_monthly_now_enqueues_period_report(monkeypatch):
    fake = FakeEnabledGroups()
    fake.add("10001")
    monkeypatch.setattr(message_pipeline, "monthly_enabled_groups", fake)
    captured: list[tuple] = []
    monkeypatch.setattr(
        groups.action_queue,
        "enqueue",
        lambda action_type, payload=None: captured.append((action_type, payload)) or {"id": "a1"},
    )
    _patch_audit_noop(monkeypatch)

    result = groups.run_monthly_now("10001", object())
    assert result["queued"] is True
    assert captured == [("period_report_now", {"group_id": "10001", "period_type": "monthly"})]


def test_run_weekly_now_409_when_not_enabled(monkeypatch):
    monkeypatch.setattr(message_pipeline, "weekly_enabled_groups", FakeEnabledGroups())
    monkeypatch.setattr(groups.action_queue, "enqueue", lambda *a, **k: {"id": "x"})
    _patch_audit_noop(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        groups.run_weekly_now("10001", object())
    assert exc.value.status_code == 409


def test_get_groups_includes_weekly_and_monthly(monkeypatch):
    wk = FakeEnabledGroups()
    wk.add("10001")
    mo = FakeEnabledGroups()
    mo.add("10002")
    monkeypatch.setattr(message_pipeline, "weekly_enabled_groups", wk)
    monkeypatch.setattr(message_pipeline, "monthly_enabled_groups", mo)
    monkeypatch.setattr(message_pipeline, "daily_enabled_groups", FakeEnabledGroups())
    monkeypatch.setattr(message_pipeline, "daily_briefing_enabled_groups", FakeEnabledGroups())

    result = groups.get_groups()
    assert result["weekly"] == ["10001"]
    assert result["monthly"] == ["10002"]
    assert result["summary"] == []
    assert result["briefing"] == []
