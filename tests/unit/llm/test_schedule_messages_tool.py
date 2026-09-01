from __future__ import annotations

import pytest

from quickquip.chat.scheduled_messages import ScheduledMessageStore
from quickquip.llm.service_parts import schedule_messages_tool as smt
from quickquip.llm.service_parts.schedule_messages_tool import ScheduleMessagesToolMixin
from quickquip.llm.tools import ToolExecutionContext


class _FakeService(ScheduleMessagesToolMixin):
    """只满足 manage_scheduled_messages handler 依赖的最小宿主（无需任何属性）。"""


def _make_context(
    group_id: int | str = 100,
    chat_type: str = "group",
) -> ToolExecutionContext:
    return ToolExecutionContext(
        group_id=group_id, user_id=42, sender_name="tester",
        provider_id="p", model="m", chat_type=chat_type,
    )


@pytest.fixture()
def tool_env(monkeypatch, tmp_path):
    """store 指向 tmp_path；调度重注册替换为记录仪（不触发 nonebot 适配层）。"""
    store = ScheduledMessageStore(tmp_path / "scheduled_messages.json")
    monkeypatch.setattr(smt, "ScheduledMessageStore", lambda: store)
    reloads: list[None] = []
    monkeypatch.setattr(smt, "_reload_scheduled_message_jobs", lambda: reloads.append(None))
    return type("ScheduleToolEnv", (), {"store": store, "reloads": reloads})()


async def test_private_chat_rejected(tool_env):
    svc = _FakeService()
    out = await svc._tool_manage_scheduled_messages(
        {"action": "list"}, _make_context(chat_type="private")
    )
    assert "该工具仅支持群聊" in out
    assert tool_env.reloads == []


async def test_create_success_persists_and_confirms(tool_env):
    svc = _FakeService()
    out = await svc._tool_manage_scheduled_messages(
        {"action": "create", "cron": "0 9 * * *", "message": "早上好"},
        _make_context(group_id=100),
    )
    jobs = tool_env.store.list()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.cron == "0 9 * * *"
    assert job.group_ids == ["100"]
    assert job.message == "早上好"
    assert job.enabled is True
    assert job.origin == "llm"
    # 默认值兼容：不传 kind / recurring 时为 text + 周期任务
    assert job.kind == "text"
    assert job.recurring is True
    assert job.id in out
    assert "0 9 * * *" in out
    assert len(tool_env.reloads) == 1


async def test_create_llm_kind(tool_env):
    svc = _FakeService()
    out = await svc._tool_manage_scheduled_messages(
        {"action": "create", "cron": "0 9 * * *", "message": "提醒大家交周报", "kind": "llm"},
        _make_context(group_id=100),
    )
    job = tool_env.store.list()[0]
    assert job.kind == "llm"
    assert job.recurring is True
    assert "LLM 任务" in out
    assert len(tool_env.reloads) == 1


async def test_create_one_shot(tool_env):
    """一次性提醒：recurring=false + cron 分/时/日/月钉到具体日期值。"""
    svc = _FakeService()
    out = await svc._tool_manage_scheduled_messages(
        {
            "action": "create",
            "cron": "0 19 2 9 *",
            "message": "提醒我看 KPL",
            "kind": "llm",
            "recurring": False,
        },
        _make_context(group_id=100),
    )
    job = tool_env.store.list()[0]
    assert job.kind == "llm"
    assert job.recurring is False
    assert job.cron == "0 19 2 9 *"
    assert "一次性" in out
    assert len(tool_env.reloads) == 1


async def test_create_unknown_kind_falls_back_to_text(tool_env):
    svc = _FakeService()
    out = await svc._tool_manage_scheduled_messages(
        {"action": "create", "cron": "0 9 * * *", "message": "早上好", "kind": "weird"},
        _make_context(group_id=100),
    )
    job = tool_env.store.list()[0]
    assert job.kind == "text"
    assert "固定文案" in out


async def test_create_invalid_cron_returns_error(tool_env):
    svc = _FakeService()
    out = await svc._tool_manage_scheduled_messages(
        {"action": "create", "cron": "bad cron", "message": "早上好"},
        _make_context(),
    )
    assert "创建定时消息失败" in out
    assert tool_env.store.list() == []
    assert tool_env.reloads == []


async def test_delete_other_group_job_rejected(tool_env):
    other = tool_env.store.add(
        cron="0 9 * * *", group_ids=["200"], message="别群任务", origin="web"
    )
    svc = _FakeService()
    out = await svc._tool_manage_scheduled_messages(
        {"action": "delete", "job_id": other.id}, _make_context(group_id=100)
    )
    assert "不存在" in out
    assert tool_env.store.get(other.id) is not None
    assert tool_env.reloads == []


async def test_set_enabled_and_delete_own_group(tool_env):
    own = tool_env.store.add(
        cron="0 9 * * *", group_ids=["100"], message="本群任务", origin="llm"
    )
    svc = _FakeService()
    out = await svc._tool_manage_scheduled_messages(
        {"action": "set_enabled", "job_id": own.id, "enabled": False},
        _make_context(group_id=100),
    )
    assert "停用" in out
    assert tool_env.store.get(own.id).enabled is False
    out = await svc._tool_manage_scheduled_messages(
        {"action": "delete", "job_id": own.id}, _make_context(group_id=100)
    )
    assert "已删除" in out
    assert tool_env.store.get(own.id) is None
    assert len(tool_env.reloads) == 2


async def test_set_enabled_requires_explicit_enabled(tool_env):
    """LLM 漏传 enabled 时必须报错，不得把停用任务静默翻回启用。"""
    own = tool_env.store.add(
        cron="0 9 * * *", group_ids=["100"], message="本群任务", enabled=False, origin="llm"
    )
    svc = _FakeService()
    out = await svc._tool_manage_scheduled_messages(
        {"action": "set_enabled", "job_id": own.id}, _make_context(group_id=100)
    )
    assert "enabled" in out
    assert tool_env.store.get(own.id).enabled is False  # 状态未被改动
    assert tool_env.reloads == []


async def test_list_filters_current_group_only(tool_env):
    mine = tool_env.store.add(
        cron="0 9 * * *", group_ids=["100"], message="本群任务", origin="llm"
    )
    other = tool_env.store.add(
        cron="30 8 * * *", group_ids=["200"], message="别群任务", origin="web"
    )
    svc = _FakeService()
    out = await svc._tool_manage_scheduled_messages(
        {"action": "list"}, _make_context(group_id=100)
    )
    assert mine.id in out
    assert "本群任务" in out
    assert "固定文案" in out
    assert "周期" in out
    assert other.id not in out
    assert "别群任务" not in out


async def test_list_empty(tool_env):
    svc = _FakeService()
    out = await svc._tool_manage_scheduled_messages({"action": "list"}, _make_context())
    assert "没有定时消息任务" in out
