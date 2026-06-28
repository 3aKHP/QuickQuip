from __future__ import annotations

import contextlib
import types

import pytest

from quickquip.adapters.nonebot import daily_summary_plugin as plugin


def _patch_period_deps(monkeypatch, *, msg_count: int = 50):
    """打桩周期生成的外部依赖。返回计数器对象便于断言调用次数。"""
    class _Counts:
        def __init__(self):
            self.read = 0
            self.generate = 0
            self.upsert = 0
            self.send = 0

    counts = _Counts()

    def fake_read_window(gid, start_ts, end_ts):
        counts.read += 1
        return [
            {"ts": float(start_ts) + i, "user_id": str(i % 5), "raw": f"msg{i}"}
            for i in range(msg_count)
        ]

    def fake_upsert(*a, **kw):
        counts.upsert += 1

    async def fake_send(*a, **kw):
        counts.send += 1

    def fake_trace(**kw):
        return contextlib.nullcontext()

    settings = types.SimpleNamespace(persona_id="p1", provider_id="prov-1", model="model-1")
    fake_svc = types.SimpleNamespace(
        config=types.SimpleNamespace(
            weekly_report=types.SimpleNamespace(
                min_messages=5, sample_per_day=3, length_hint=200, model_cascade=["model-1"],
            ),
            monthly_report=types.SimpleNamespace(
                min_messages=5, sample_per_day=3, length_hint=300, model_cascade=["model-1"],
            ),
            personas={"p1": object()},
        ),
        get_group_settings=lambda gid: settings,
    )

    async def fake_generate(sampled, persona, group_id, **kw):
        counts.generate += 1
        return ("周期报告正文", "model-1")

    monkeypatch.setattr(plugin, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(plugin, "get_llm_service", lambda: fake_svc)
    monkeypatch.setattr(plugin, "stats_tracker", types.SimpleNamespace(get_stats=lambda gid: None))
    monkeypatch.setattr(plugin, "wordcloud_collector", types.SimpleNamespace(read_window=fake_read_window))
    monkeypatch.setattr(plugin, "sample_messages_by_day", lambda msgs, per_day: msgs)
    monkeypatch.setattr(plugin, "generate_period_report", fake_generate)
    monkeypatch.setattr(plugin, "period_store", types.SimpleNamespace(upsert=fake_upsert))
    monkeypatch.setattr(plugin, "send_long_group_message", fake_send)
    monkeypatch.setattr(plugin, "bot_action_trace", fake_trace)

    return counts


@pytest.mark.asyncio
async def test_run_period_generation_uses_service_get_group_settings(monkeypatch):
    """回归 Bot HIGH：_run_period_generation 必须用 svc.get_group_settings(group_id)。
    旧实现误用不存在的 llm_config.resolve_group_settings，每次生成都 AttributeError 崩溃。
    """
    counts = _patch_period_deps(monkeypatch, msg_count=50)

    result = await plugin._run_period_generation(
        "10001", plugin.PERIOD_WEEKLY, 1_000.0, 100_000.0, "2026-W26",
    )

    assert result == ("周期报告正文", "model-1")
    assert counts.generate == 1


@pytest.mark.asyncio
async def test_generate_period_one_reads_window_once_and_persists(monkeypatch):
    """回归 Bot MEDIUM：_generate_period_one 只通过 _run_period_generation 读一次窗口。
    旧实现 caller 与 _run_period_generation 各读一次（双倍 I/O），且传入的 period_key/label 被丢弃。
    """
    counts = _patch_period_deps(monkeypatch, msg_count=50)

    await plugin._generate_period_one("10001", plugin.PERIOD_WEEKLY)

    assert counts.read == 1      # 不再重复读窗口
    assert counts.upsert == 1    # 定时 job 路径入库


@pytest.mark.asyncio
async def test_send_period_report_now_does_not_persist(monkeypatch):
    """回归 Bot MEDIUM：命令触发的 _send_period_report_now 不应入库。
    旧实现经 _generate_period_one 触发 upsert（published_at=NULL），定时 publish job 会重复发布。
    """
    counts = _patch_period_deps(monkeypatch, msg_count=50)
    monkeypatch.setattr(plugin, "_period_enabled_groups", lambda pt: types.SimpleNamespace(
        contains=lambda gid: True, all_groups=lambda: [],
        add=lambda gid: None, remove=lambda gid: None,
    ))
    monkeypatch.setattr(plugin, "_on_cooldown", lambda gid: False)
    monkeypatch.setattr(plugin, "_mark_triggered", lambda gid: None)

    await plugin._send_period_report_now(10001, plugin.PERIOD_WEEKLY, bot=object())

    assert counts.upsert == 0    # 不入库
    assert counts.send == 1      # 但确实发送了


@pytest.mark.asyncio
async def test_run_period_generation_populates_name_table_from_stats(monkeypatch):
    """回归 Bot LOW #9：name_table 应从 stats_tracker.user_names 填充，
    否则周报/月报里成员会显示 QQ 号而非昵称。
    """
    _patch_period_deps(monkeypatch, msg_count=50)
    monkeypatch.setattr(plugin, "stats_tracker", types.SimpleNamespace(
        get_stats=lambda gid: types.SimpleNamespace(user_names={"123": "小明", "456": "小红"}),
    ))

    captured: dict = {}

    async def capture_generate(sampled, persona, group_id, **kw):
        captured["name_table"] = kw["name_table"]
        return ("正文", "model-1")

    monkeypatch.setattr(plugin, "generate_period_report", capture_generate)

    await plugin._run_period_generation("10001", plugin.PERIOD_WEEKLY, 1_000.0, 100_000.0, "2026-W26")

    assert captured["name_table"] == {"123": "小明", "456": "小红"}


@pytest.mark.asyncio
async def test_send_period_report_now_raises_not_enabled(monkeypatch):
    """回归 Bot LOW #5：未开启抛 PeriodReportNotEnabledError（非通用 RuntimeError）。"""
    _patch_period_deps(monkeypatch)
    monkeypatch.setattr(plugin, "_period_enabled_groups", lambda pt: types.SimpleNamespace(
        contains=lambda gid: False, all_groups=lambda: [],
        add=lambda gid: None, remove=lambda gid: None,
    ))
    with pytest.raises(plugin.PeriodReportNotEnabledError):
        await plugin._send_period_report_now(10001, plugin.PERIOD_WEEKLY, bot=object())


@pytest.mark.asyncio
async def test_send_period_report_now_raises_cooldown(monkeypatch):
    """回归 Bot LOW #5：冷却中抛 PeriodReportCooldownError。"""
    _patch_period_deps(monkeypatch)
    monkeypatch.setattr(plugin, "_period_enabled_groups", lambda pt: types.SimpleNamespace(
        contains=lambda gid: True, all_groups=lambda: [],
        add=lambda gid: None, remove=lambda gid: None,
    ))
    monkeypatch.setattr(plugin, "_on_cooldown", lambda gid: True)
    with pytest.raises(plugin.PeriodReportCooldownError):
        await plugin._send_period_report_now(10001, plugin.PERIOD_WEEKLY, bot=object())


@pytest.mark.asyncio
async def test_send_period_report_now_raises_generation_failed(monkeypatch):
    """回归 Bot LOW #5：生成失败（_run_period_generation 返回 None）抛 GenerationFailedError。"""
    _patch_period_deps(monkeypatch)
    monkeypatch.setattr(plugin, "_period_enabled_groups", lambda pt: types.SimpleNamespace(
        contains=lambda gid: True, all_groups=lambda: [],
        add=lambda gid: None, remove=lambda gid: None,
    ))
    monkeypatch.setattr(plugin, "_on_cooldown", lambda gid: False)
    monkeypatch.setattr(plugin, "_mark_triggered", lambda gid: None)

    async def fake_run_gen(*a, **kw):
        return None

    monkeypatch.setattr(plugin, "_run_period_generation", fake_run_gen)
    with pytest.raises(plugin.PeriodReportGenerationFailedError):
        await plugin._send_period_report_now(10001, plugin.PERIOD_WEEKLY, bot=object())
