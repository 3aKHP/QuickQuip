"""scheduler_plugin 定时消息与节日问候的发送形状测试（CQ 安全收口）。"""

from __future__ import annotations

import asyncio
import contextlib
import types

from nonebot.adapters.onebot.v11 import Message

from quickquip.adapters.nonebot import scheduler_plugin


class FakeCronScheduler:
    def __init__(self):
        self.jobs: dict[str, dict] = {}

    def add_job(self, func, trigger, *, id, replace_existing, **cron_kwargs):
        self.jobs[id] = {"func": func, "trigger": trigger, "cron": cron_kwargs}


def _capture_bot(sent: list[dict]):
    async def fake_send_group_msg(**kwargs):
        sent.append(kwargs)

    return types.SimpleNamespace(send_group_msg=fake_send_group_msg)


def _assert_single_text_segment(message, expected_text: str):
    assert isinstance(message, Message)
    assert len(message) == 1
    assert message[0].type == "text"
    assert message[0].data["text"] == expected_text


def test_scheduled_message_sends_text_segment(monkeypatch):
    """定时消息以 text 段发出；配置里的字符串群号归一为 int。"""
    sent: list[dict] = []
    bot = _capture_bot(sent)
    sched = FakeCronScheduler()
    monkeypatch.setattr(scheduler_plugin, "scheduler", sched)
    monkeypatch.setattr(scheduler_plugin, "nonebot", types.SimpleNamespace(get_bot=lambda: bot))
    monkeypatch.setattr(
        scheduler_plugin,
        "SCHEDULED_MESSAGES",
        [{"cron": "0 9 * * *", "group_ids": [123, "456"], "message": "早安 [CQ:at,qq=all]"}],
    )
    monkeypatch.setattr(
        scheduler_plugin, "bot_action_trace", lambda **kw: contextlib.nullcontext()
    )

    scheduler_plugin._register_jobs()
    asyncio.run(sched.jobs["scheduled_msg_0"]["func"]())

    assert [item["group_id"] for item in sent] == [123, 456]
    for item in sent:
        _assert_single_text_segment(item["message"], "早安 [CQ:at,qq=all]")


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
