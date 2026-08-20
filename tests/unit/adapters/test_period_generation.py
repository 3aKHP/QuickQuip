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
    """回归 Bot MEDIUM：命令触发的 send_period_report_now 不应入库。
    旧实现经 _generate_period_one 触发 upsert（published_at=NULL），定时 publish job 会重复发布。
    """
    counts = _patch_period_deps(monkeypatch, msg_count=50)
    monkeypatch.setattr(plugin, "_period_enabled_groups", lambda pt: types.SimpleNamespace(
        contains=lambda gid: True, all_groups=lambda: [],
        add=lambda gid: None, remove=lambda gid: None,
    ))
    monkeypatch.setattr(plugin, "_on_period_cooldown", lambda gid: False)
    monkeypatch.setattr(plugin, "_mark_period_triggered", lambda gid: None)

    await plugin.send_period_report_now(10001, plugin.PERIOD_WEEKLY, bot=object())

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
        await plugin.send_period_report_now(10001, plugin.PERIOD_WEEKLY, bot=object())


@pytest.mark.asyncio
async def test_send_period_report_now_raises_cooldown(monkeypatch):
    """回归 Bot LOW #5：冷却中抛 PeriodReportCooldownError。"""
    _patch_period_deps(monkeypatch)
    monkeypatch.setattr(plugin, "_period_enabled_groups", lambda pt: types.SimpleNamespace(
        contains=lambda gid: True, all_groups=lambda: [],
        add=lambda gid: None, remove=lambda gid: None,
    ))
    monkeypatch.setattr(plugin, "_on_period_cooldown", lambda gid: True)
    with pytest.raises(plugin.PeriodReportCooldownError):
        await plugin.send_period_report_now(10001, plugin.PERIOD_WEEKLY, bot=object())


@pytest.mark.asyncio
async def test_send_period_report_now_raises_generation_failed(monkeypatch):
    """回归 Bot LOW #5：生成失败（_run_period_generation 返回 None）抛 GenerationFailedError。"""
    _patch_period_deps(monkeypatch)
    monkeypatch.setattr(plugin, "_period_enabled_groups", lambda pt: types.SimpleNamespace(
        contains=lambda gid: True, all_groups=lambda: [],
        add=lambda gid: None, remove=lambda gid: None,
    ))
    monkeypatch.setattr(plugin, "_on_period_cooldown", lambda gid: False)
    monkeypatch.setattr(plugin, "_mark_period_triggered", lambda gid: None)

    async def fake_run_gen(*a, **kw):
        return None

    monkeypatch.setattr(plugin, "_run_period_generation", fake_run_gen)
    with pytest.raises(plugin.PeriodReportGenerationFailedError):
        await plugin.send_period_report_now(10001, plugin.PERIOD_WEEKLY, bot=object())


def test_period_cooldown_independent_of_daily():
    """回归 Bot MEDIUM：周报/月报冷却字典独立于每日总结，同群两类"立即生成"不互相阻挡。"""
    plugin._last_manual_trigger.clear()
    plugin._last_period_manual_trigger.clear()
    plugin._mark_triggered("10001")
    assert plugin._on_cooldown("10001")
    assert not plugin._on_period_cooldown("10001")
    plugin._mark_period_triggered("10002")
    assert plugin._on_period_cooldown("10002")
    assert not plugin._on_cooldown("10002")


# ── characterization: v1.12.1 生成编排下沉前的行为钉住 ──────────────────


@pytest.mark.asyncio
async def test_run_period_generation_skips_below_min_messages(monkeypatch):
    """钉住：窗口消息数 < min_messages 时返回 None 且不调用 LLM。"""
    counts = _patch_period_deps(monkeypatch, msg_count=3)  # min_messages=5

    result = await plugin._run_period_generation(
        "10001", plugin.PERIOD_WEEKLY, 1_000.0, 100_000.0, "2026-W26",
    )

    assert result is None
    assert counts.generate == 0


@pytest.mark.asyncio
async def test_run_period_generation_proceeds_at_exact_min_messages(monkeypatch):
    """钉住：消息数恰好等于 min_messages 时照常生成（边界含等号）。"""
    counts = _patch_period_deps(monkeypatch, msg_count=5)  # min_messages=5

    result = await plugin._run_period_generation(
        "10001", plugin.PERIOD_WEEKLY, 1_000.0, 100_000.0, "2026-W26",
    )

    assert result == ("周期报告正文", "model-1")
    assert counts.generate == 1


@pytest.mark.asyncio
async def test_run_period_generation_returns_none_when_sample_empty(monkeypatch):
    """钉住：分天采样结果为空时返回 None 且不调用 LLM。"""
    counts = _patch_period_deps(monkeypatch, msg_count=50)
    monkeypatch.setattr(plugin, "sample_messages_by_day", lambda msgs, per_day: [])

    result = await plugin._run_period_generation(
        "10001", plugin.PERIOD_WEEKLY, 1_000.0, 100_000.0, "2026-W26",
    )

    assert result is None
    assert counts.generate == 0


@pytest.mark.asyncio
async def test_run_period_generation_falls_back_to_first_persona(monkeypatch):
    """钉住：群 persona_id 不在 personas 表时回退到字典里第一个 persona。"""
    first, second = object(), object()
    counts = _patch_period_deps(monkeypatch, msg_count=50)

    fake_svc = plugin.get_llm_service()
    fake_svc.config.personas = {"a": first, "b": second}
    fake_svc.get_group_settings = lambda gid: types.SimpleNamespace(
        persona_id="missing", provider_id="prov-1", model="model-1",
    )

    captured: dict = {}

    async def capture_generate(sampled, persona, group_id, **kw):
        captured["persona"] = persona
        return ("正文", "model-1")

    monkeypatch.setattr(plugin, "generate_period_report", capture_generate)

    await plugin._run_period_generation(
        "10001", plugin.PERIOD_WEEKLY, 1_000.0, 100_000.0, "2026-W26",
    )

    assert captured["persona"] is first
    assert counts.generate == 0  # fake_generate 被 capture_generate 替换


@pytest.mark.asyncio
async def test_run_period_generation_returns_none_when_no_persona(monkeypatch):
    """钉住：personas 为空表时返回 None 且不调用 LLM。"""
    counts = _patch_period_deps(monkeypatch, msg_count=50)
    plugin.get_llm_service().config.personas = {}

    result = await plugin._run_period_generation(
        "10001", plugin.PERIOD_WEEKLY, 1_000.0, 100_000.0, "2026-W26",
    )

    assert result is None
    assert counts.generate == 0


@pytest.mark.asyncio
async def test_run_period_generation_swallows_llm_exception(monkeypatch):
    """钉住：generate_period_report 抛异常时返回 None（不外抛）。"""
    _patch_period_deps(monkeypatch, msg_count=50)

    async def boom(*a, **kw):
        raise RuntimeError("llm down")

    monkeypatch.setattr(plugin, "generate_period_report", boom)

    result = await plugin._run_period_generation(
        "10001", plugin.PERIOD_WEEKLY, 1_000.0, 100_000.0, "2026-W26",
    )

    assert result is None


@pytest.mark.asyncio
async def test_run_period_generation_monthly_uses_monthly_config(monkeypatch):
    """钉住：monthly 走 monthly_report 配置（独立 min_messages），period_kind 透传。"""
    counts = _patch_period_deps(monkeypatch, msg_count=50)
    # 抬高 monthly 门槛到窗口消息数以上 → monthly 跳过而 weekly 不跳过
    plugin.get_llm_service().config.monthly_report.min_messages = 100

    result = await plugin._run_period_generation(
        "10001", plugin.PERIOD_MONTHLY, 1_000.0, 100_000.0, "2026-05",
    )
    assert result is None
    assert counts.generate == 0

    captured: dict = {}

    async def capture_generate(sampled, persona, group_id, **kw):
        captured["period_kind"] = kw["period_kind"]
        captured["length_hint"] = kw["length_hint"]
        return ("正文", "model-1")

    monkeypatch.setattr(plugin, "generate_period_report", capture_generate)
    plugin.get_llm_service().config.monthly_report.min_messages = 5

    result = await plugin._run_period_generation(
        "10001", plugin.PERIOD_MONTHLY, 1_000.0, 100_000.0, "2026-05",
    )
    assert result == ("正文", "model-1")
    assert captured["period_kind"] == plugin.PERIOD_MONTHLY
    assert captured["length_hint"] == 300  # monthly_report.length_hint


@pytest.mark.asyncio
async def test_generate_period_one_upserts_with_window_period_key(monkeypatch):
    """钉住：_generate_period_one 用 compute_period_window(now) 的 period_key 入库并返回结果。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    counts = _patch_period_deps(monkeypatch, msg_count=50)
    upserts: list[tuple] = []
    monkeypatch.setattr(
        plugin, "period_store",
        types.SimpleNamespace(upsert=lambda *a: upserts.append(a)),
    )

    now = datetime(2026, 5, 4, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))  # 周一
    result = await plugin._generate_period_one("10001", plugin.PERIOD_WEEKLY, now=now)

    assert result == ("周期报告正文", "model-1")
    assert counts.upsert == 0  # period_store 已被整体替换
    assert upserts == [("10001", plugin.PERIOD_WEEKLY, "2026-W18", "周期报告正文", "model-1")]


@pytest.mark.asyncio
async def test_job_generate_period_reports_noop_without_groups(monkeypatch):
    """钉住：无启用群时不生成、不读窗口。"""
    counts = _patch_period_deps(monkeypatch, msg_count=50)
    monkeypatch.setattr(plugin, "_period_enabled_groups", lambda pt: types.SimpleNamespace(
        all_groups=lambda: [],
    ))

    await plugin._job_generate_period_reports(plugin.PERIOD_WEEKLY)

    assert counts.read == 0
    assert counts.generate == 0


@pytest.mark.asyncio
async def test_job_generate_period_reports_single_group_failure_isolated(monkeypatch):
    """钉住：单群生成抛异常不影响其他群，job 本身不外抛。"""
    _patch_period_deps(monkeypatch, msg_count=50)
    calls: list[str] = []

    async def fake_generate_one(group_id, period_type, *, now=None):
        calls.append(group_id)
        if group_id == "10001":
            raise RuntimeError("boom")
        return None

    monkeypatch.setattr(plugin, "_period_enabled_groups", lambda pt: types.SimpleNamespace(
        all_groups=lambda: ["10001", "10002"],
    ))
    monkeypatch.setattr(plugin, "_generate_period_one", fake_generate_one)

    await plugin._job_generate_period_reports(plugin.PERIOD_WEEKLY)

    assert sorted(calls) == ["10001", "10002"]


def _patch_publish_period_deps(monkeypatch):
    """打桩周期发布依赖，返回 (events, bot)。"""
    events: list = []
    bot = types.SimpleNamespace(name="fake-bot")

    async def fake_send(_bot, group_id, content, **kw):
        events.append(("send", group_id))

    monkeypatch.setattr(plugin, "nonebot", types.SimpleNamespace(get_bot=lambda: bot))
    monkeypatch.setattr(plugin, "send_long_group_message", fake_send)
    monkeypatch.setattr(plugin, "bot_action_trace", lambda **kw: contextlib.nullcontext())
    return events, bot


@pytest.mark.asyncio
async def test_publish_period_one_marks_after_send(monkeypatch):
    """钉住：send 成功后才 mark_published。"""
    events, bot = _patch_publish_period_deps(monkeypatch)
    monkeypatch.setattr(plugin, "period_store", types.SimpleNamespace(
        mark_published=lambda gid, pt, key: events.append(("mark", gid, pt, key)),
    ))

    row = {"group_id": "10001", "period_key": "2026-W18", "content": "正文", "model_used": "m"}
    await plugin._publish_period_one(bot, row, plugin.PERIOD_WEEKLY)

    assert events == [("send", 10001), ("mark", "10001", plugin.PERIOD_WEEKLY, "2026-W18")]


@pytest.mark.asyncio
async def test_publish_period_one_send_failure_not_marked(monkeypatch):
    """钉住：发送失败时不 mark_published，异常不外抛。"""
    events, bot = _patch_publish_period_deps(monkeypatch)

    async def failing_send(_bot, group_id, content, **kw):
        events.append(("send", group_id))
        raise RuntimeError("network down")

    monkeypatch.setattr(plugin, "send_long_group_message", failing_send)
    monkeypatch.setattr(plugin, "period_store", types.SimpleNamespace(
        mark_published=lambda gid, pt, key: events.append(("mark", gid, pt, key)),
    ))

    row = {"group_id": "10001", "period_key": "2026-W18", "content": "正文", "model_used": "m"}
    await plugin._publish_period_one(bot, row, plugin.PERIOD_WEEKLY)

    assert events == [("send", 10001)]


@pytest.mark.asyncio
async def test_job_publish_period_reports_only_enabled_groups(monkeypatch):
    """钉住：周期发布 job 只发仍在启用集合里的群；未发布但已禁用的群被跳过。"""
    events, bot = _patch_publish_period_deps(monkeypatch)
    rows = [
        {"group_id": "10001", "period_key": "2026-W18", "content": "a", "model_used": "m"},
        {"group_id": "10002", "period_key": "2026-W18", "content": "b", "model_used": "m"},
    ]
    monkeypatch.setattr(plugin, "period_store", types.SimpleNamespace(
        get_unpublished=lambda pt: rows,
        mark_published=lambda gid, pt, key: events.append(("mark", gid, pt, key)),
    ))
    monkeypatch.setattr(plugin, "weekly_enabled_groups", types.SimpleNamespace(
        all_groups=lambda: ["10001"],
    ))

    await plugin._job_publish_period_reports(plugin.PERIOD_WEEKLY)

    sends = [e for e in events if e[0] == "send"]
    assert sends == [("send", 10001)]


def test_period_enabled_groups_rejects_unknown_type():
    """钉住：_period_enabled_groups 对未知 period_type 抛 ValueError。"""
    with pytest.raises(ValueError, match="未知 period_type"):
        plugin._period_enabled_groups("yearly")
