from __future__ import annotations

import pytest

from quickquip.common.bot_action_trace import (
    bot_action_trace,
    build_bot_action_trace_payload,
    current_bot_action_trace,
    install_nonebot_api_trace_hook,
    log_bot_action_trace,
    overlay_bot_action_trace,
)


def test_bot_action_trace_payload_uses_context():
    with bot_action_trace(
        trigger_kind="awakening",
        reason_code="awakening_interest",
        reason_detail="兴趣话题匹配：LLM",
        rule_name="awakening_interest",
        chat_type="group",
        group_id=1000000001,
        user_id=42,
        incoming_message_id="m1",
        incoming_preview="llmy没有比",
        reply_preview="我来了",
        llm_used=True,
        provider_id="openai",
        model="gpt-test",
        source="unit",
    ):
        payload = build_bot_action_trace_payload(
            api="send_group_msg",
            data={"group_id": 1000000001, "message": "我来了"},
            result={"message_id": 99},
        )

    assert payload["coverage_gap"] is False
    assert payload["trigger_kind"] == "awakening"
    assert payload["reason_code"] == "awakening_interest"
    assert payload["reason_detail"] == "兴趣话题匹配：LLM"
    assert payload["group_id"] == "1000000001"
    assert payload["user_id"] == "42"
    assert payload["sent_message_id"] == "99"
    assert payload["incoming_preview"] == ""
    assert payload["reply_preview"] == ""
    assert payload["content_redacted"] is True
    assert payload["llm_used"] is True
    assert payload["provider_id"] == "openai"
    assert payload["model"] == "gpt-test"


def test_payload_marks_missing_context_as_coverage_gap():
    payload = build_bot_action_trace_payload(
        api="send_private_msg",
        data={"user_id": 7, "message": "hi"},
    )

    assert payload["coverage_gap"] is True
    assert payload["reason_code"] == "unknown.unattributed"
    assert payload["chat_type"] == "private"
    assert payload["user_id"] == "7"
    assert payload["reply_preview"] == ""
    assert payload["content_redacted"] is True


def test_payload_summarizes_forward_message_types_without_content():
    payload = build_bot_action_trace_payload(
        api="send_group_forward_msg",
        data={
            "group_id": 1,
            "messages": [
                {"type": "node", "data": {"content": "secret"}},
                {"type": "node", "data": {"content": "more secret"}},
            ],
        },
    )

    assert payload["message_types"] == ["node", "node"]
    assert payload["reply_preview"] == ""
    assert payload["content_redacted"] is True


def test_overlay_ignores_unknown_fields():
    with bot_action_trace(trigger_kind="command", reason_code="command.demo"):
        with overlay_bot_action_trace(reason_code="command.specific", unknown_field="ignored") as trace:
            assert trace.reason_code == "command.specific"
            assert not hasattr(trace, "unknown_field")


@pytest.mark.asyncio
async def test_install_nonebot_api_trace_hook_logs_action(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "quickquip.common.bot_action_trace.log_bot_action_trace",
        lambda **kwargs: calls.append(kwargs) or {},
    )

    class FakeBot:
        _called_hooks = []

        @classmethod
        def on_called_api(cls, func):
            cls._called_hooks.append(func)
            return func

    installed = install_nonebot_api_trace_hook(FakeBot)
    assert installed is True

    await FakeBot._called_hooks[-1](
        object(),
        None,
        "send_group_msg",
        {"group_id": 1, "message": "hello"},
        {"message_id": 2},
    )
    await FakeBot._called_hooks[-1](
        object(),
        None,
        "get_forward_msg",
        {"message_id": 1},
        {},
    )

    assert len(calls) == 1
    assert calls[0]["api"] == "send_group_msg"


def test_log_bot_action_trace_returns_payload(monkeypatch):
    messages = []
    monkeypatch.setattr("quickquip.common.bot_action_trace._logger.info", lambda *args: messages.append(args))

    payload = log_bot_action_trace(api="send_msg", data={"message": "hello"})

    assert payload["coverage_gap"] is True
    assert messages
    assert messages[0][0].startswith("BOT_ACTION_TRACE ")
    assert current_bot_action_trace() is None
