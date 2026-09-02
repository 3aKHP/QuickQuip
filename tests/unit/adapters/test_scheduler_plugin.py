"""scheduler_plugin 定时消息与节日问候的发送形状测试（CQ 安全收口）。"""

from __future__ import annotations

import asyncio
import contextlib
import types

from nonebot.adapters.onebot.v11 import Message

from quickquip.adapters.nonebot import scheduler_plugin
from quickquip.chat.scheduled_messages import ScheduledMessageStore
from tests.fixtures.scheduled_cron import future_one_shot_cron


class FakeCronScheduler:
    def __init__(self):
        self.jobs: dict[str, dict] = {}

    def add_job(self, func, trigger, *, id, replace_existing, **cron_kwargs):
        self.jobs[id] = {"func": func, "trigger": trigger, "cron": cron_kwargs}

    def get_jobs(self):
        return [types.SimpleNamespace(id=job_id) for job_id in self.jobs]

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)


def _capture_bot(sent: list[dict]):
    async def fake_send_group_msg(**kwargs):
        sent.append(kwargs)

    return types.SimpleNamespace(send_group_msg=fake_send_group_msg)


def _assert_single_text_segment(message, expected_text: str):
    assert isinstance(message, Message)
    assert len(message) == 1
    assert message[0].type == "text"
    assert message[0].data["text"] == expected_text


def test_scheduled_message_sends_text_segment(monkeypatch, tmp_path):
    """定时消息以 text 段发出；配置里的字符串群号归一为 int。"""
    sent: list[dict] = []
    bot = _capture_bot(sent)
    sched = FakeCronScheduler()
    monkeypatch.setattr(scheduler_plugin, "scheduler", sched)
    monkeypatch.setattr(scheduler_plugin, "nonebot", types.SimpleNamespace(get_bot=lambda: bot))
    monkeypatch.setattr(
        scheduler_plugin, "bot_action_trace", lambda **kw: contextlib.nullcontext()
    )

    store = ScheduledMessageStore(tmp_path / "sm.json")
    store.add(
        cron="0 9 * * *",
        group_ids=[123, "456"],
        message="早安 [CQ:at,qq=all]",
        origin="web",
    )

    count = scheduler_plugin.reload_scheduled_message_jobs(store)
    assert count == 1
    job_id = f"scheduled_msg_{store.list()[0].id}"
    asyncio.run(sched.jobs[job_id]["func"]())

    assert [item["group_id"] for item in sent] == [123, 456]
    for item in sent:
        _assert_single_text_segment(item["message"], "早安 [CQ:at,qq=all]")


def test_one_shot_job_deleted_after_fire(monkeypatch, tmp_path):
    """一次性（recurring=False）任务触发后自动从存储与调度器中删除。"""
    sent: list[dict] = []
    bot = _capture_bot(sent)
    sched = FakeCronScheduler()
    monkeypatch.setattr(scheduler_plugin, "scheduler", sched)
    monkeypatch.setattr(scheduler_plugin, "nonebot", types.SimpleNamespace(get_bot=lambda: bot))
    monkeypatch.setattr(
        scheduler_plugin, "bot_action_trace", lambda **kw: contextlib.nullcontext()
    )

    store = ScheduledMessageStore(tmp_path / "sm.json")
    store.add(cron=future_one_shot_cron(), group_ids=[123], message="看KPL", recurring=False)

    scheduler_plugin.reload_scheduled_message_jobs(store)
    job_id = f"scheduled_msg_{store.list()[0].id}"
    asyncio.run(sched.jobs[job_id]["func"]())

    assert len(sent) == 1
    assert store.list() == []
    assert job_id not in sched.jobs


def test_llm_task_generates_and_sends(monkeypatch, tmp_path):
    """llm 类任务把 prompt 以合成 user 消息喂给 LLM，生成结果发群。"""
    sent: list[dict] = []

    async def fake_send_group_msg(**kwargs):
        sent.append(kwargs)

    bot = types.SimpleNamespace(send_group_msg=fake_send_group_msg)
    sched = FakeCronScheduler()
    monkeypatch.setattr(scheduler_plugin, "scheduler", sched)
    monkeypatch.setattr(scheduler_plugin, "nonebot", types.SimpleNamespace(get_bot=lambda: bot))
    monkeypatch.setattr(
        scheduler_plugin, "bot_action_trace", lambda **kw: contextlib.nullcontext()
    )

    generate_calls: list[dict] = []

    async def fake_generate_reply(**kwargs):
        generate_calls.append(kwargs)
        return {"reply": "七点了，该看KPL了", "images": []}

    fake_svc = types.SimpleNamespace(
        generate_reply=fake_generate_reply,
        recent_message_buffer=types.SimpleNamespace(list_recent=lambda gid, limit: []),
    )

    import quickquip.app.message_pipeline as mp
    import quickquip.chat.awakening as awakening_mod

    monkeypatch.setattr(mp, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(mp, "get_llm_service", lambda: fake_svc)
    monkeypatch.setattr(
        mp, "rule_switch", types.SimpleNamespace(is_enabled=lambda gid, name: True)
    )
    monkeypatch.setattr(awakening_mod, "_is_group_llm_enabled", lambda svc, gid: True)

    store = ScheduledMessageStore(tmp_path / "sm.json")
    store.add(
        cron="0 19 * * *",
        group_ids=[123],
        message="提醒大家看KPL",
        kind="llm",
        origin="llm",
    )

    scheduler_plugin.reload_scheduled_message_jobs(store)
    job_id = f"scheduled_msg_{store.list()[0].id}"
    asyncio.run(sched.jobs[job_id]["func"]())

    assert len(generate_calls) == 1
    call = generate_calls[0]
    assert call["store_user_message"] is False
    assert "【任务指令】提醒大家看KPL" in call["prompt"]
    assert [item["group_id"] for item in sent] == [123]
    _assert_single_text_segment(sent[0]["message"], "七点了，该看KPL了")


def test_llm_task_skipped_when_rule_disabled(monkeypatch, tmp_path):
    """rule_switch 关闭 scheduled_message_llm 时，llm 类任务跳过该群。"""
    sent: list[dict] = []

    async def fake_send_group_msg(**kwargs):
        sent.append(kwargs)

    bot = types.SimpleNamespace(send_group_msg=fake_send_group_msg)
    sched = FakeCronScheduler()
    monkeypatch.setattr(scheduler_plugin, "scheduler", sched)
    monkeypatch.setattr(scheduler_plugin, "nonebot", types.SimpleNamespace(get_bot=lambda: bot))
    monkeypatch.setattr(
        scheduler_plugin, "bot_action_trace", lambda **kw: contextlib.nullcontext()
    )

    import quickquip.app.message_pipeline as mp

    monkeypatch.setattr(
        mp, "rule_switch", types.SimpleNamespace(is_enabled=lambda gid, name: False)
    )

    store = ScheduledMessageStore(tmp_path / "sm.json")
    store.add(cron="0 19 * * *", group_ids=[123], message="提醒大家看KPL", kind="llm")

    scheduler_plugin.reload_scheduled_message_jobs(store)
    job_id = f"scheduled_msg_{store.list()[0].id}"
    asyncio.run(sched.jobs[job_id]["func"]())

    assert sent == []


def test_festival_greeting_sends_text_segment(monkeypatch):
    """节日问候以 text 段发出（内容为静态代码字符串，做同类防御性收口）。"""
    sent: list[dict] = []
    bot = _capture_bot(sent)
    sched = FakeCronScheduler()
    monkeypatch.setattr(scheduler_plugin, "scheduler", sched)
    monkeypatch.setattr(scheduler_plugin, "nonebot", types.SimpleNamespace(get_bot=lambda: bot))
    monkeypatch.setattr(
        scheduler_plugin, "bot_action_trace", lambda **kw: contextlib.nullcontext()
    )

    # festival 链在注册函数内 lazy import，patch 源模块属性即可
    import quickquip.app.message_pipeline as mp
    import quickquip.chat.festival as festival_mod

    monkeypatch.setattr(
        festival_mod, "check_today_festival", lambda: types.SimpleNamespace(name="测试节")
    )
    monkeypatch.setattr(festival_mod, "get_festival_greeting", lambda: "节日快乐")
    monkeypatch.setattr(
        mp, "daily_enabled_groups", types.SimpleNamespace(all_groups=lambda: ["789"])
    )

    scheduler_plugin._register_festival_job()
    asyncio.run(sched.jobs["festival_check"]["func"]())

    assert [item["group_id"] for item in sent] == [789]
    _assert_single_text_segment(sent[0]["message"], "【测试节】节日快乐")
