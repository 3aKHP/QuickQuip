from __future__ import annotations

from quickquip.adapters.nonebot.trace import traced_on_command
from quickquip.common.bot_action_trace import current_bot_action_trace


class _FakeEvent:
    message_type = "group"
    group_id = 100
    user_id = 200
    message_id = "m-1"

    @staticmethod
    def get_message():
        return "/demo hello"


class _FakeMatcher:
    def __init__(self):
        self.decorated = None

    def handle(self):
        def deco(fn):
            self.decorated = fn
            return fn

        return deco


def test_traced_on_command_wraps_handler_with_command_reason():
    matcher = _FakeMatcher()

    def on_command(name, **kwargs):
        assert name == "demo"
        return matcher

    traced = traced_on_command(on_command)
    command = traced("demo", priority=10)
    captured = {}

    @command.handle()
    async def _(event):
        trace = current_bot_action_trace()
        captured["trace"] = trace
        return "ok"

    import asyncio

    result = asyncio.run(matcher.decorated(_FakeEvent()))

    assert result == "ok"
    trace = captured["trace"]
    assert trace is not None
    assert trace.trigger_kind == "command"
    assert trace.reason_code == "command.demo"
    assert trace.group_id == "100"
    assert trace.user_id == "200"
    assert trace.incoming_message_id == "m-1"
