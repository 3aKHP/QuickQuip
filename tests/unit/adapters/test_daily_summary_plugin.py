from __future__ import annotations

import contextlib
from datetime import datetime
import types
from zoneinfo import ZoneInfo

import pytest

from quickquip.adapters.nonebot import daily_summary_plugin as daily_summary_plugin


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        current = cls(2026, 5, 4, 6, 0, tzinfo=LOCAL_TZ)
        return current if tz is None else current.astimezone(tz)


@pytest.mark.asyncio
async def test_job_generate_summaries_dispatches_enabled_groups(monkeypatch):
    calls: list[tuple[str, float, float, str, str]] = []

    async def fake_generate_one(group_id, start_ts, end_ts, date_label, summary_date):
        calls.append((group_id, start_ts, end_ts, date_label, summary_date))

    class _EnabledGroups:
        @staticmethod
        def all_groups():
            return ["10001", "10002"]

    monkeypatch.setattr(daily_summary_plugin, "datetime", _FixedDateTime)
    monkeypatch.setattr(daily_summary_plugin, "daily_enabled_groups", _EnabledGroups())
    monkeypatch.setattr(daily_summary_plugin, "_generate_one", fake_generate_one)

    await daily_summary_plugin._job_generate_summaries()

    assert [group_id for group_id, *_ in calls] == ["10001", "10002"]
    assert all(summary_date == "2026-05-03" for *_, summary_date in calls)
    assert all(
        date_label == "2026年05月03日 06:00 至 05月04日 06:00"
        for *_, date_label, _summary_date in calls
    )


@pytest.mark.asyncio
async def test_send_daily_summary_now_reuses_manual_generation(monkeypatch):
    calls: list[tuple[str, float, float, str]] = []

    class _EnabledGroups:
        @staticmethod
        def contains(group_id):
            return group_id == "123456"

    async def fake_run_generation(group_id, start_ts, end_ts, date_label):
        calls.append((group_id, start_ts, end_ts, date_label))
        return "summary text", "model-a"

    sent: list[tuple[int, str]] = []

    async def fake_send_long_message(_bot, group_id, content):
        sent.append((group_id, content))

    monkeypatch.setattr(daily_summary_plugin, "datetime", _FixedDateTime)
    monkeypatch.setattr(daily_summary_plugin, "daily_enabled_groups", _EnabledGroups())
    monkeypatch.setattr(daily_summary_plugin.daily_collector, "read_window", lambda *args, **kwargs: ["m1", "m2"])
    monkeypatch.setattr(
        daily_summary_plugin,
        "get_llm_service",
        lambda: types.SimpleNamespace(config=types.SimpleNamespace(daily_summary=types.SimpleNamespace(min_messages=1))),
    )
    monkeypatch.setattr(daily_summary_plugin, "_on_cooldown", lambda group_id: False)
    monkeypatch.setattr(daily_summary_plugin, "_mark_triggered", lambda group_id: None)
    monkeypatch.setattr(daily_summary_plugin, "_run_generation", fake_run_generation)
    monkeypatch.setattr(daily_summary_plugin, "_send_long_message", fake_send_long_message)
    before_generate_calls: list[str] = []

    async def before_generate():
        before_generate_calls.append("called")

    result = await daily_summary_plugin.send_daily_summary_now("123456", types.SimpleNamespace(), before_generate)

    assert result == {"model_used": "model-a", "char_count": len("summary text")}
    assert sent == [(123456, "summary text")]
    assert before_generate_calls == ["called"]
    assert calls[0][0] == "123456"
    assert calls[0][3] == "2026年05月03日 06:00 至 05月04日 06:00"


@pytest.mark.asyncio
async def test_send_daily_summary_now_reports_not_enough_messages(monkeypatch):
    class _EnabledGroups:
        @staticmethod
        def contains(group_id):
            return group_id == "123456"

    monkeypatch.setattr(daily_summary_plugin, "datetime", _FixedDateTime)
    monkeypatch.setattr(daily_summary_plugin, "daily_enabled_groups", _EnabledGroups())
    monkeypatch.setattr(daily_summary_plugin.daily_collector, "read_window", lambda *args, **kwargs: ["m1"])
    monkeypatch.setattr(
        daily_summary_plugin,
        "get_llm_service",
        lambda: types.SimpleNamespace(config=types.SimpleNamespace(daily_summary=types.SimpleNamespace(min_messages=2))),
    )
    monkeypatch.setattr(daily_summary_plugin, "_on_cooldown", lambda group_id: False)
    monkeypatch.setattr(daily_summary_plugin, "_mark_triggered", lambda group_id: None)

    with pytest.raises(
        daily_summary_plugin.DailySummaryInsufficientMessagesError,
        match="not enough messages: 1/2",
    ):
        await daily_summary_plugin.send_daily_summary_now("123456", types.SimpleNamespace())


# ── characterization: v1.12.1 生成编排下沉前的行为钉住 ──────────────────


def _fixed_datetime(year, month, day, hour, minute=0):
    class _Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            current = cls(year, month, day, hour, minute, tzinfo=LOCAL_TZ)
            return current if tz is None else current.astimezone(tz)

    return _Fixed


def _patch_run_generation_deps(monkeypatch, *, messages, min_messages=5, personas=None,
                               persona_id="p1", stats=None):
    """打桩 _run_generation 的外部依赖，返回捕获字典。"""
    captured: dict = {"generate_calls": []}

    if personas is None:
        personas = {"p1": object()}

    fake_svc = types.SimpleNamespace(
        config=types.SimpleNamespace(
            daily_summary=types.SimpleNamespace(min_messages=min_messages),
            personas=personas,
        ),
        get_group_settings=lambda gid: types.SimpleNamespace(
            persona_id=persona_id, provider_id="prov-1", model="model-1",
        ),
    )

    async def fake_generate(**kw):
        captured["generate_calls"].append(kw)
        return ("日报正文", "model-1")

    monkeypatch.setattr(daily_summary_plugin, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(daily_summary_plugin, "get_llm_service", lambda: fake_svc)
    monkeypatch.setattr(
        daily_summary_plugin, "daily_collector",
        types.SimpleNamespace(read_window=lambda gid, s, e: list(messages)),
    )
    monkeypatch.setattr(
        daily_summary_plugin, "stats_tracker",
        types.SimpleNamespace(get_stats=lambda gid: stats),
    )
    monkeypatch.setattr(daily_summary_plugin, "generate_daily_summary", fake_generate)
    return captured


@pytest.mark.asyncio
async def test_run_generation_skips_when_below_min_messages(monkeypatch):
    """钉住：窗口消息数 < min_messages 时返回 None 且不调用 LLM。"""
    captured = _patch_run_generation_deps(monkeypatch, messages=["m1", "m2"], min_messages=5)

    result = await daily_summary_plugin._run_generation("10001", 1.0, 2.0, "label")

    assert result is None
    assert captured["generate_calls"] == []


@pytest.mark.asyncio
async def test_run_generation_proceeds_at_exact_min_messages(monkeypatch):
    """钉住：消息数恰好等于 min_messages 时照常生成（边界含等号）。"""
    captured = _patch_run_generation_deps(
        monkeypatch, messages=["m1", "m2", "m3"], min_messages=3,
    )

    result = await daily_summary_plugin._run_generation("10001", 1.0, 2.0, "label")

    assert result == ("日报正文", "model-1")
    assert len(captured["generate_calls"]) == 1


@pytest.mark.asyncio
async def test_run_generation_falls_back_to_first_persona(monkeypatch):
    """钉住：群 persona_id 不在 personas 表时回退到字典里第一个 persona。"""
    first, second = object(), object()
    captured = _patch_run_generation_deps(
        monkeypatch, messages=["m1"], min_messages=1,
        personas={"a": first, "b": second}, persona_id="missing",
    )

    result = await daily_summary_plugin._run_generation("10001", 1.0, 2.0, "label")

    assert result == ("日报正文", "model-1")
    assert captured["generate_calls"][0]["persona"] is first


@pytest.mark.asyncio
async def test_run_generation_returns_none_when_no_persona_available(monkeypatch):
    """钉住：personas 为空表时返回 None 且不调用 LLM。"""
    captured = _patch_run_generation_deps(
        monkeypatch, messages=["m1"], min_messages=1, personas={},
    )

    result = await daily_summary_plugin._run_generation("10001", 1.0, 2.0, "label")

    assert result is None
    assert captured["generate_calls"] == []


@pytest.mark.asyncio
async def test_run_generation_name_table_empty_when_stats_missing(monkeypatch):
    """钉住：stats_tracker 无该群统计时 name_table 为空 dict。"""
    captured = _patch_run_generation_deps(
        monkeypatch, messages=["m1"], min_messages=1, stats=None,
    )

    await daily_summary_plugin._run_generation("10001", 1.0, 2.0, "label")

    assert captured["generate_calls"][0]["name_table"] == {}


@pytest.mark.asyncio
async def test_run_generation_name_table_from_stats_user_names(monkeypatch):
    """钉住：name_table 取自 stats.user_names（成员昵称映射）。"""
    stats = types.SimpleNamespace(user_names={"123": "小明"})
    captured = _patch_run_generation_deps(
        monkeypatch, messages=["m1"], min_messages=1, stats=stats,
    )

    await daily_summary_plugin._run_generation("10001", 1.0, 2.0, "label")

    assert captured["generate_calls"][0]["name_table"] == {"123": "小明"}


@pytest.mark.asyncio
async def test_run_generation_swallows_llm_exception(monkeypatch):
    """钉住：generate_daily_summary 抛异常时返回 None（不外抛）。"""
    _patch_run_generation_deps(monkeypatch, messages=["m1"], min_messages=1)

    async def boom(**kw):
        raise RuntimeError("llm down")

    monkeypatch.setattr(daily_summary_plugin, "generate_daily_summary", boom)

    result = await daily_summary_plugin._run_generation("10001", 1.0, 2.0, "label")

    assert result is None


@pytest.mark.asyncio
async def test_generate_one_persists_on_success(monkeypatch):
    """钉住：_generate_one 生成成功时以 summary_date 入库。"""
    upserts: list[tuple] = []
    monkeypatch.setattr(
        daily_summary_plugin, "daily_store",
        types.SimpleNamespace(upsert=lambda *a: upserts.append(a)),
    )

    async def fake_run(group_id, start_ts, end_ts, date_label):
        return ("正文", "model-x")

    monkeypatch.setattr(daily_summary_plugin, "_run_generation", fake_run)

    await daily_summary_plugin._generate_one("10001", 1.0, 2.0, "label", "2026-05-03")

    assert upserts == [("10001", "2026-05-03", "正文", "model-x")]


@pytest.mark.asyncio
async def test_generate_one_skips_persist_when_generation_returns_none(monkeypatch):
    """钉住：_run_generation 返回 None 时不入库。"""
    upserts: list[tuple] = []
    monkeypatch.setattr(
        daily_summary_plugin, "daily_store",
        types.SimpleNamespace(upsert=lambda *a: upserts.append(a)),
    )

    async def fake_run(group_id, start_ts, end_ts, date_label):
        return None

    monkeypatch.setattr(daily_summary_plugin, "_run_generation", fake_run)

    await daily_summary_plugin._generate_one("10001", 1.0, 2.0, "label", "2026-05-03")

    assert upserts == []


@pytest.mark.asyncio
async def test_job_generate_summaries_window_at_exactly_0600(monkeypatch):
    """钉住：恰好 06:00 触发时窗口为 [昨日06:00, 今日06:00)。"""
    calls: list[tuple] = []

    async def fake_generate_one(group_id, start_ts, end_ts, date_label, summary_date):
        calls.append((group_id, start_ts, end_ts, date_label, summary_date))

    monkeypatch.setattr(daily_summary_plugin, "datetime", _fixed_datetime(2026, 5, 4, 6, 0))
    monkeypatch.setattr(
        daily_summary_plugin, "daily_enabled_groups",
        types.SimpleNamespace(all_groups=lambda: ["10001"]),
    )
    monkeypatch.setattr(daily_summary_plugin, "_generate_one", fake_generate_one)

    await daily_summary_plugin._job_generate_summaries()

    expected_start = datetime(2026, 5, 3, 6, 0, tzinfo=LOCAL_TZ).timestamp()
    expected_end = datetime(2026, 5, 4, 6, 0, tzinfo=LOCAL_TZ).timestamp()
    assert calls == [(
        "10001", expected_start, expected_end,
        "2026年05月03日 06:00 至 05月04日 06:00", "2026-05-03",
    )]


@pytest.mark.asyncio
async def test_job_generate_summaries_window_crosses_month_boundary(monkeypatch):
    """钉住：月初 06:00 触发时窗口跨月，summary_date 取上月最后一天。"""
    calls: list[tuple] = []

    async def fake_generate_one(group_id, start_ts, end_ts, date_label, summary_date):
        calls.append((group_id, start_ts, end_ts, date_label, summary_date))

    monkeypatch.setattr(daily_summary_plugin, "datetime", _fixed_datetime(2026, 6, 1, 6, 0))
    monkeypatch.setattr(
        daily_summary_plugin, "daily_enabled_groups",
        types.SimpleNamespace(all_groups=lambda: ["10001"]),
    )
    monkeypatch.setattr(daily_summary_plugin, "_generate_one", fake_generate_one)

    await daily_summary_plugin._job_generate_summaries()

    assert calls[0][1] == datetime(2026, 5, 31, 6, 0, tzinfo=LOCAL_TZ).timestamp()
    assert calls[0][2] == datetime(2026, 6, 1, 6, 0, tzinfo=LOCAL_TZ).timestamp()
    assert calls[0][3] == "2026年05月31日 06:00 至 06月01日 06:00"
    assert calls[0][4] == "2026-05-31"


@pytest.mark.asyncio
async def test_job_generate_summaries_window_when_fired_before_0600(monkeypatch):
    """钉住现状：00:30 触发时窗口 end 仍是"今天 06:00"（未来时刻），
    summary_date 取昨天。这是当前实现的实际行为（cron 正常不会此时触发）。"""
    calls: list[tuple] = []

    async def fake_generate_one(group_id, start_ts, end_ts, date_label, summary_date):
        calls.append((group_id, start_ts, end_ts, date_label, summary_date))

    monkeypatch.setattr(daily_summary_plugin, "datetime", _fixed_datetime(2026, 5, 4, 0, 30))
    monkeypatch.setattr(
        daily_summary_plugin, "daily_enabled_groups",
        types.SimpleNamespace(all_groups=lambda: ["10001"]),
    )
    monkeypatch.setattr(daily_summary_plugin, "_generate_one", fake_generate_one)

    await daily_summary_plugin._job_generate_summaries()

    assert calls[0][1] == datetime(2026, 5, 3, 6, 0, tzinfo=LOCAL_TZ).timestamp()
    assert calls[0][2] == datetime(2026, 5, 4, 6, 0, tzinfo=LOCAL_TZ).timestamp()
    assert calls[0][4] == "2026-05-03"


@pytest.mark.asyncio
async def test_job_generate_summaries_single_group_failure_isolated(monkeypatch):
    """钉住：单群生成抛异常不影响其他群，job 本身不外抛。"""
    calls: list[str] = []

    async def fake_generate_one(group_id, start_ts, end_ts, date_label, summary_date):
        calls.append(group_id)
        if group_id == "10001":
            raise RuntimeError("boom")

    monkeypatch.setattr(daily_summary_plugin, "datetime", _fixed_datetime(2026, 5, 4, 6, 0))
    monkeypatch.setattr(
        daily_summary_plugin, "daily_enabled_groups",
        types.SimpleNamespace(all_groups=lambda: ["10001", "10002"]),
    )
    monkeypatch.setattr(daily_summary_plugin, "_generate_one", fake_generate_one)

    await daily_summary_plugin._job_generate_summaries()

    assert sorted(calls) == ["10001", "10002"]


def _patch_publish_deps(monkeypatch):
    """打桩 _publish_one / _job_publish_summaries 依赖，返回事件日志。"""
    events: list = []
    bot = types.SimpleNamespace(name="fake-bot")

    async def fake_send(_bot, group_id, content):
        events.append(("send", group_id))

    monkeypatch.setattr(daily_summary_plugin, "nonebot", types.SimpleNamespace(get_bot=lambda: bot))
    monkeypatch.setattr(daily_summary_plugin, "_send_long_message", fake_send)
    monkeypatch.setattr(
        daily_summary_plugin, "bot_action_trace",
        lambda **kw: contextlib.nullcontext(),
    )
    return events, bot


@pytest.mark.asyncio
async def test_publish_one_marks_then_deletes_window_files_in_order(monkeypatch):
    """钉住发布顺序：send → mark_published → delete_date_file(summary_date)
    → delete_date_file(summary_date - 1)（确认送达后才删 JSONL，覆盖窗口两天）。"""
    events, bot = _patch_publish_deps(monkeypatch)
    monkeypatch.setattr(
        daily_summary_plugin, "daily_store",
        types.SimpleNamespace(mark_published=lambda gid, d: events.append(("mark", gid, d))),
    )
    monkeypatch.setattr(
        daily_summary_plugin, "daily_collector",
        types.SimpleNamespace(delete_date_file=lambda gid, d: events.append(("delete", gid, d))),
    )

    import datetime as dt

    row = {"group_id": "10001", "summary_date": "2026-05-03", "content": "正文", "model_used": "m"}
    await daily_summary_plugin._publish_one(bot, row)

    assert events == [
        ("send", 10001),
        ("mark", "10001", "2026-05-03"),
        ("delete", "10001", dt.date(2026, 5, 3)),
        ("delete", "10001", dt.date(2026, 5, 2)),
    ]


@pytest.mark.asyncio
async def test_publish_one_send_failure_keeps_store_and_files(monkeypatch):
    """钉住：发送失败时不 mark_published、不删 JSONL，异常不外抛。"""
    events, bot = _patch_publish_deps(monkeypatch)

    async def failing_send(_bot, group_id, content):
        events.append(("send", group_id))
        raise RuntimeError("network down")

    monkeypatch.setattr(daily_summary_plugin, "_send_long_message", failing_send)
    monkeypatch.setattr(
        daily_summary_plugin, "daily_store",
        types.SimpleNamespace(mark_published=lambda gid, d: events.append(("mark", gid, d))),
    )
    monkeypatch.setattr(
        daily_summary_plugin, "daily_collector",
        types.SimpleNamespace(delete_date_file=lambda gid, d: events.append(("delete", gid, d))),
    )

    row = {"group_id": "10001", "summary_date": "2026-05-03", "content": "正文", "model_used": "m"}
    await daily_summary_plugin._publish_one(bot, row)

    assert events == [("send", 10001)]


@pytest.mark.asyncio
async def test_job_publish_summaries_only_publishes_enabled_groups(monkeypatch):
    """钉住：发布 job 只处理仍在启用集合里的群；已禁用群的未发布行被跳过。"""
    events, bot = _patch_publish_deps(monkeypatch)
    rows = [
        {"group_id": "10001", "summary_date": "2026-05-03", "content": "a", "model_used": "m"},
        {"group_id": "10002", "summary_date": "2026-05-03", "content": "b", "model_used": "m"},
    ]
    monkeypatch.setattr(
        daily_summary_plugin, "daily_store",
        types.SimpleNamespace(
            get_unpublished=lambda: rows,
            mark_published=lambda gid, d: events.append(("mark", gid, d)),
        ),
    )
    monkeypatch.setattr(
        daily_summary_plugin, "daily_collector",
        types.SimpleNamespace(delete_date_file=lambda gid, d: events.append(("delete", gid, d))),
    )
    monkeypatch.setattr(
        daily_summary_plugin, "daily_enabled_groups",
        types.SimpleNamespace(all_groups=lambda: ["10001"]),
    )

    await daily_summary_plugin._job_publish_summaries()

    sends = [e for e in events if e[0] == "send"]
    assert sends == [("send", 10001)]


@pytest.mark.asyncio
async def test_job_publish_summaries_noop_without_unpublished(monkeypatch):
    """钉住：无未发布记录时不发送任何消息。"""
    events, bot = _patch_publish_deps(monkeypatch)
    monkeypatch.setattr(
        daily_summary_plugin, "daily_store",
        types.SimpleNamespace(get_unpublished=lambda: []),
    )

    await daily_summary_plugin._job_publish_summaries()

    assert events == []


@pytest.mark.asyncio
async def test_send_daily_summary_now_window_starts_yesterday_0600(monkeypatch):
    """钉住：手动触发窗口为 [昨日06:00, 当前时刻)，date_label 按此刻渲染。"""
    read_calls: list[tuple] = []

    def fake_read_window(group_id, start_ts, end_ts):
        read_calls.append((group_id, start_ts, end_ts))
        return ["m1"]

    run_calls: list[tuple] = []

    async def fake_run_generation(group_id, start_ts, end_ts, date_label):
        run_calls.append((group_id, start_ts, end_ts, date_label))
        return ("正文", "model-a")

    monkeypatch.setattr(daily_summary_plugin, "datetime", _fixed_datetime(2026, 5, 4, 15, 30))
    monkeypatch.setattr(
        daily_summary_plugin, "daily_enabled_groups",
        types.SimpleNamespace(contains=lambda gid: True),
    )
    monkeypatch.setattr(daily_summary_plugin.daily_collector, "read_window", fake_read_window)
    monkeypatch.setattr(
        daily_summary_plugin,
        "get_llm_service",
        lambda: types.SimpleNamespace(
            config=types.SimpleNamespace(daily_summary=types.SimpleNamespace(min_messages=1)),
        ),
    )
    monkeypatch.setattr(daily_summary_plugin, "_on_cooldown", lambda gid: False)
    monkeypatch.setattr(daily_summary_plugin, "_mark_triggered", lambda gid: None)
    monkeypatch.setattr(daily_summary_plugin, "_run_generation", fake_run_generation)
    async def fake_send_long(*a, **kw):
        return None

    monkeypatch.setattr(daily_summary_plugin, "_send_long_message", fake_send_long)

    await daily_summary_plugin.send_daily_summary_now("10001", types.SimpleNamespace())

    expected_start = datetime(2026, 5, 3, 6, 0, tzinfo=LOCAL_TZ).timestamp()
    expected_end = datetime(2026, 5, 4, 15, 30, tzinfo=LOCAL_TZ).timestamp()
    assert read_calls == [("10001", expected_start, expected_end)]
    assert run_calls[0][3] == "2026年05月03日 06:00 至 05月04日 15:30"


@pytest.mark.asyncio
async def test_send_daily_summary_now_raises_typed_not_enabled_and_cooldown(monkeypatch):
    """钉住类型化异常契约（P3 改造后）：未开启 / 冷却分别抛对应类型，str 文本保持兼容。"""
    monkeypatch.setattr(
        daily_summary_plugin, "daily_enabled_groups",
        types.SimpleNamespace(contains=lambda gid: False),
    )
    with pytest.raises(daily_summary_plugin.DailySummaryNotEnabledError) as exc_info:
        await daily_summary_plugin.send_daily_summary_now("10001", types.SimpleNamespace())
    assert str(exc_info.value) == "daily summary is not enabled for this group"

    monkeypatch.setattr(
        daily_summary_plugin, "daily_enabled_groups",
        types.SimpleNamespace(contains=lambda gid: True),
    )
    monkeypatch.setattr(daily_summary_plugin, "_on_cooldown", lambda gid: True)
    with pytest.raises(daily_summary_plugin.DailySummaryCooldownError) as exc_info:
        await daily_summary_plugin.send_daily_summary_now("10001", types.SimpleNamespace())
    assert str(exc_info.value) == "summary generation is on cooldown"


@pytest.mark.asyncio
async def test_send_daily_summary_now_insufficient_messages_carries_counts(monkeypatch):
    """钉住：消息不足抛 DailySummaryInsufficientMessagesError，携带 current/minimum 属性。"""
    monkeypatch.setattr(daily_summary_plugin, "datetime", _fixed_datetime(2026, 5, 4, 15, 30))
    monkeypatch.setattr(
        daily_summary_plugin, "daily_enabled_groups",
        types.SimpleNamespace(contains=lambda gid: True),
    )
    monkeypatch.setattr(
        daily_summary_plugin.daily_collector, "read_window",
        lambda *a, **kw: ["m1", "m2", "m3"],
    )
    monkeypatch.setattr(
        daily_summary_plugin,
        "get_llm_service",
        lambda: types.SimpleNamespace(
            config=types.SimpleNamespace(daily_summary=types.SimpleNamespace(min_messages=10)),
        ),
    )
    monkeypatch.setattr(daily_summary_plugin, "_on_cooldown", lambda gid: False)
    monkeypatch.setattr(daily_summary_plugin, "_mark_triggered", lambda gid: None)

    with pytest.raises(daily_summary_plugin.DailySummaryInsufficientMessagesError) as exc_info:
        await daily_summary_plugin.send_daily_summary_now("10001", types.SimpleNamespace())
    assert exc_info.value.current == 3
    assert exc_info.value.minimum == 10
    assert str(exc_info.value) == "not enough messages: 3/10"


@pytest.mark.asyncio
async def test_send_daily_summary_now_raises_when_generation_returns_none(monkeypatch):
    """钉住：_run_generation 返回 None 时抛 DailySummaryGenerationFailedError。"""
    monkeypatch.setattr(daily_summary_plugin, "datetime", _fixed_datetime(2026, 5, 4, 15, 30))
    monkeypatch.setattr(
        daily_summary_plugin, "daily_enabled_groups",
        types.SimpleNamespace(contains=lambda gid: True),
    )
    monkeypatch.setattr(
        daily_summary_plugin.daily_collector, "read_window",
        lambda *a, **kw: ["m1"],
    )
    monkeypatch.setattr(
        daily_summary_plugin,
        "get_llm_service",
        lambda: types.SimpleNamespace(
            config=types.SimpleNamespace(daily_summary=types.SimpleNamespace(min_messages=1)),
        ),
    )
    monkeypatch.setattr(daily_summary_plugin, "_on_cooldown", lambda gid: False)
    monkeypatch.setattr(daily_summary_plugin, "_mark_triggered", lambda gid: None)

    async def fake_run(*a):
        return None

    monkeypatch.setattr(daily_summary_plugin, "_run_generation", fake_run)

    with pytest.raises(daily_summary_plugin.DailySummaryGenerationFailedError) as exc_info:
        await daily_summary_plugin.send_daily_summary_now("10001", types.SimpleNamespace())
    assert str(exc_info.value) == "summary generation skipped or failed"
