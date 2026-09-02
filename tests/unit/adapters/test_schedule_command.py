from __future__ import annotations

import pytest

from quickquip.adapters.nonebot.command_parts import scheduler as mod
from quickquip.chat.scheduled_messages import ScheduledMessageStore
from tests.fixtures.scheduled_cron import future_one_shot_cron


class _FinishSentinel(Exception):
    """模拟 nonebot 的 finish() 抛出异常终止 handler 的行为。"""


class _FakeCommand:
    """捕获注册的 handler 与 finish 回复。"""

    def __init__(self):
        self.handlers = []
        self.finished: list[str] = []

    def handle(self):
        def deco(fn):
            self.handlers.append(fn)
            return fn

        return deco

    async def finish(self, msg: str = "") -> None:
        self.finished.append(str(msg))
        raise _FinishSentinel()


class _FakeSender:
    def __init__(self, role: str = "admin"):
        self.role = role


class _FakeEvent:
    def __init__(self, text: str, *, group_id: int = 10001, role: str = "admin"):
        self.message_type = "group"
        self.group_id = group_id
        self.user_id = 42
        self.sender = _FakeSender(role)
        self._text = text

    def get_message(self):
        return self._text


@pytest.fixture
def cmd_setup(monkeypatch, tmp_path):
    store = ScheduledMessageStore(tmp_path / "scheduled_messages.json")
    monkeypatch.setattr(mod, "scheduled_message_store", store)
    cmd = _FakeCommand()
    mod.register_scheduler_commands(lambda *a, **k: cmd, None, None)
    return store, cmd


async def _run(cmd, event):
    with pytest.raises(_FinishSentinel):
        await cmd.handlers[0](event)


@pytest.mark.asyncio
async def test_add_success_writes_store(cmd_setup):
    store, cmd = cmd_setup
    await _run(cmd, _FakeEvent("/schedule add 0 9 * * * 早安"))

    jobs = store.list()
    assert len(jobs) == 1
    assert jobs[0].cron == "0 9 * * *"
    assert jobs[0].group_ids == ["10001"]
    assert jobs[0].message == "早安"
    assert jobs[0].origin == "command"
    assert jobs[0].kind == "text"
    assert jobs[0].recurring is True
    assert jobs[0].enabled is True
    assert jobs[0].id in cmd.finished[0]
    assert "0 9 * * *" in cmd.finished[0]


@pytest.mark.asyncio
async def test_add_llm_kind(cmd_setup):
    store, cmd = cmd_setup
    await _run(cmd, _FakeEvent("/schedule add llm 0 9 * * * 用东北话问大家早安"))

    jobs = store.list()
    assert len(jobs) == 1
    assert jobs[0].kind == "llm"
    assert jobs[0].recurring is True
    assert jobs[0].cron == "0 9 * * *"
    assert jobs[0].message == "用东北话问大家早安"


@pytest.mark.asyncio
async def test_add_once_non_recurring(cmd_setup):
    store, cmd = cmd_setup
    cron = future_one_shot_cron()
    await _run(cmd, _FakeEvent(f"/schedule add once {cron} 今晚看KPL"))

    jobs = store.list()
    assert len(jobs) == 1
    assert jobs[0].kind == "text"
    assert jobs[0].recurring is False
    assert jobs[0].cron == cron
    assert jobs[0].message == "今晚看KPL"


@pytest.mark.asyncio
async def test_add_llm_once_flags_any_order(cmd_setup):
    store, cmd = cmd_setup
    cron = future_one_shot_cron()
    await _run(cmd, _FakeEvent(f"/schedule add llm once {cron} 提醒大家今晚看KPL"))
    await _run(cmd, _FakeEvent("/schedule add once llm 30 8 * * * 催大家打卡"))

    jobs = store.list()
    assert len(jobs) == 2
    assert jobs[0].kind == "llm"
    assert jobs[0].recurring is False
    assert jobs[0].message == "提醒大家今晚看KPL"
    assert jobs[1].kind == "llm"
    assert jobs[1].recurring is False
    assert jobs[1].cron == "30 8 * * *"
    assert jobs[1].message == "催大家打卡"


@pytest.mark.asyncio
async def test_add_flags_stripped_before_cron_validation(cmd_setup):
    """标记剥离后 cron 段数不足仍应报用法，而不是把标记当 cron 字段。"""
    store, cmd = cmd_setup
    await _run(cmd, _FakeEvent("/schedule add llm once 0 9 * *"))

    assert store.list() == []
    assert "用法" in cmd.finished[0]


@pytest.mark.asyncio
async def test_add_message_keeps_spaces_and_extra_text(cmd_setup):
    store, cmd = cmd_setup
    await _run(cmd, _FakeEvent("/schedule add 30 8 * * 1-5 记得 打卡 哦"))

    jobs = store.list()
    assert len(jobs) == 1
    assert jobs[0].cron == "30 8 * * 1-5"
    assert jobs[0].message == "记得 打卡 哦"


@pytest.mark.asyncio
async def test_add_invalid_cron_replies_error(cmd_setup):
    store, cmd = cmd_setup
    await _run(cmd, _FakeEvent("/schedule add a b c d e 你好"))

    assert store.list() == []
    assert "cron" in cmd.finished[0]


@pytest.mark.asyncio
async def test_add_missing_args_shows_usage(cmd_setup):
    store, cmd = cmd_setup
    await _run(cmd, _FakeEvent("/schedule add 0 9 * *"))

    assert store.list() == []
    assert "用法" in cmd.finished[0]


@pytest.mark.asyncio
async def test_del_other_group_task_rejected(cmd_setup):
    store, cmd = cmd_setup
    job = store.add(cron="0 9 * * *", group_ids=["20002"], message="别的群")

    await _run(cmd, _FakeEvent(f"/schedule del {job.id}"))

    assert f"未找到属于本群的任务：{job.id}" == cmd.finished[0]
    assert store.get(job.id) is not None


@pytest.mark.asyncio
async def test_del_own_group_task_success(cmd_setup):
    store, cmd = cmd_setup
    job = store.add(cron="0 9 * * *", group_ids=["10001"], message="本群消息")

    await _run(cmd, _FakeEvent(f"/schedule del {job.id}"))

    assert f"已删除定时消息：{job.id}" == cmd.finished[0]
    assert store.get(job.id) is None


@pytest.mark.asyncio
async def test_on_off_toggle_and_idempotent(cmd_setup):
    store, cmd = cmd_setup
    job = store.add(cron="0 9 * * *", group_ids=["10001"], message="本群消息")

    await _run(cmd, _FakeEvent(f"/schedule off {job.id}"))
    assert store.get(job.id).enabled is False
    assert f"已停用定时消息：{job.id}" == cmd.finished[-1]

    await _run(cmd, _FakeEvent(f"/schedule off {job.id}"))
    assert f"任务 {job.id} 已是停用状态" == cmd.finished[-1]

    await _run(cmd, _FakeEvent(f"/schedule on {job.id}"))
    assert store.get(job.id).enabled is True
    assert f"已启用定时消息：{job.id}" == cmd.finished[-1]


@pytest.mark.asyncio
async def test_on_other_group_task_rejected(cmd_setup):
    store, cmd = cmd_setup
    job = store.add(cron="0 9 * * *", group_ids=["20002"], message="别的群", enabled=False)

    await _run(cmd, _FakeEvent(f"/schedule on {job.id}"))

    assert f"未找到属于本群的任务：{job.id}" == cmd.finished[0]
    assert store.get(job.id).enabled is False


@pytest.mark.asyncio
async def test_list_empty(cmd_setup):
    _, cmd = cmd_setup
    await _run(cmd, _FakeEvent("/schedule list"))
    assert cmd.finished == ["本群暂无定时消息"]


@pytest.mark.asyncio
async def test_list_filters_current_group_and_shows_status(cmd_setup):
    store, cmd = cmd_setup
    own = store.add(cron="0 9 * * *", group_ids=["10001"], message="本群早安")
    store.add(cron="0 10 * * *", group_ids=["20002"], message="别群消息", enabled=False)

    await _run(cmd, _FakeEvent("/schedule list"))

    reply = cmd.finished[0]
    assert own.id in reply
    assert "0 9 * * *" in reply
    assert "启用" in reply
    assert "本群早安" in reply
    assert "别群消息" not in reply


@pytest.mark.asyncio
async def test_list_shows_kind_and_once_tags(cmd_setup):
    store, cmd = cmd_setup
    plain = store.add(cron="0 9 * * *", group_ids=["10001"], message="普通文案")
    llm_job = store.add(cron="0 10 * * *", group_ids=["10001"], message="LLM 指令", kind="llm")
    once_job = store.add(
        cron=future_one_shot_cron(),
        group_ids=["10001"],
        message="一次性提醒",
        recurring=False,
    )

    await _run(cmd, _FakeEvent("/schedule list"))

    reply = cmd.finished[0]
    lines = {line.split()[1]: line for line in reply.splitlines() if line.startswith("- ")}
    assert "[LLM]" not in lines[plain.id]
    assert "[一次性]" not in lines[plain.id]
    assert "[LLM]" in lines[llm_job.id]
    assert "[一次性]" not in lines[llm_job.id]
    assert "[一次性]" in lines[once_job.id]
    assert "[LLM]" not in lines[once_job.id]


@pytest.mark.asyncio
async def test_bare_command_shows_usage(cmd_setup):
    _, cmd = cmd_setup
    await _run(cmd, _FakeEvent("/schedule"))
    assert "用法" in cmd.finished[0]
    assert "/schedule add" in cmd.finished[0]


@pytest.mark.asyncio
async def test_private_chat_rejected(cmd_setup):
    _, cmd = cmd_setup
    event = _FakeEvent("/schedule list")
    event.message_type = "private"
    await _run(cmd, event)
    assert cmd.finished == ["私聊不支持 /schedule"]


@pytest.mark.asyncio
async def test_non_admin_rejected(cmd_setup):
    _, cmd = cmd_setup
    await _run(cmd, _FakeEvent("/schedule list", role="member"))
    assert cmd.finished == ["仅管理员可执行此操作"]
