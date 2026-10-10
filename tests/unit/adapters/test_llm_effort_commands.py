"""`/llm effort` 子命令：status 查询无门槛；变更走内联管理门；非法档不写库。

反馈文案为三层口径状态行（配置档 / 覆盖档 / 钳制后生效档），变更后
重新解析设置输出同一行。
"""
from __future__ import annotations

import pytest

from quickquip.adapters.nonebot.command_parts import llm as llm_part


class _FinishSentinel(Exception):
    """模拟 nonebot finish() 终止 handler。"""


class _FakeLlmCmd:
    def __init__(self) -> None:
        self.finished: list[str] = []
        self.handler = None

    def handle(self):
        def deco(fn):
            self.handler = fn
            return fn

        return deco

    async def finish(self, msg: str = "") -> None:
        self.finished.append(str(msg))
        raise _FinishSentinel()

    async def send(self, msg) -> None:
        return None


class _FakeEvent:
    """私聊事件：绕过管理员判定，聚焦 effort 子命令分支。"""

    def __init__(self, text: str) -> None:
        self._text = text
        self.message_type = "private"
        self.user_id = 2002
        self.group_id = None

    def get_message(self) -> str:
        return self._text


class _FakeGroupEvent:
    """群聊非管理员事件：变更必须被管理门拦下。"""

    def __init__(self, text: str) -> None:
        self._text = text
        self.message_type = "group"
        self.user_id = 2002
        self.group_id = 1001

    def get_message(self) -> str:
        return self._text


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str]] = []
        self.status_line = "思考档位：gpt-test 自身默认档。本群未单独设置。"

    def format_effort_status(self, chat_id, chat_type: str = "group") -> str:
        return self.status_line

    def set_chat_reasoning_effort(self, chat_id, effort, chat_type: str = "group") -> None:
        self.calls.append((effort, chat_type))


_SEG = type("Seg", (), {
    "text": staticmethod(lambda v: v),
    "image": staticmethod(lambda v: v),
    "record": staticmethod(lambda v: v),
})


def _register() -> _FakeLlmCmd:
    cmd = _FakeLlmCmd()
    llm_part.register_llm_commands(
        lambda name, **kw: (cmd if name == "llm" else _FakeLlmCmd()), list, _SEG
    )
    return cmd


def _patch_service(monkeypatch: pytest.MonkeyPatch, service: _FakeService) -> None:
    monkeypatch.setattr(llm_part, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(llm_part, "get_llm_service", lambda: service)


async def _dispatch(monkeypatch, text: str, event_cls=_FakeEvent) -> tuple[list[str], _FakeService]:
    service = _FakeService()
    _patch_service(monkeypatch, service)
    cmd = _register()
    with pytest.raises(_FinishSentinel):
        await cmd.handler(event_cls(text))
    return cmd.finished, service


async def test_effort_status_is_query_only(monkeypatch):
    """裸 effort 与 effort status 等价，只读展示，不触发写入，也不附 400 提示。"""
    for text in ("/llm effort", "/llm effort status"):
        finished, service = await _dispatch(monkeypatch, text)
        assert finished == ["思考档位：gpt-test 自身默认档。本群未单独设置。"]
        assert service.calls == []


async def test_effort_set_and_default(monkeypatch):
    """档位写入与 default 清覆盖（None）都路由到 service，反馈为状态行；
    仅实际设档附 400 排查提示。"""
    finished, service = await _dispatch(monkeypatch, "/llm effort high")
    assert service.calls == [("high", "private")]
    assert finished == [
        "思考档位：gpt-test 自身默认档。本群未单独设置。"
        "\n若切换后出现 400 等 4xx 错误，说明该渠道或模型不支持此档位，"
        "发送 /llm effort default 即可恢复。"
    ]

    finished, service = await _dispatch(monkeypatch, "/llm effort default")
    assert service.calls == [(None, "private")]
    assert len(finished) == 1
    assert "400" not in finished[0]


async def test_effort_unknown_tier_is_noop(monkeypatch):
    """不认识的档位只落用法提示，不触发任何写入。"""
    finished, service = await _dispatch(monkeypatch, "/llm effort extreme")
    assert service.calls == []
    assert len(finished) == 1
    assert "用法" in finished[0]


async def test_effort_mutation_gated_for_non_admin(monkeypatch):
    """群聊非管理员：变更被拦；status 查询仍放行。"""
    finished, service = await _dispatch(monkeypatch, "/llm effort high", _FakeGroupEvent)
    assert service.calls == []
    assert finished == ["仅管理员可执行此操作"]

    finished, service = await _dispatch(monkeypatch, "/llm effort status", _FakeGroupEvent)
    assert service.calls == []
    assert finished == ["思考档位：gpt-test 自身默认档。本群未单独设置。"]


async def test_effort_mutation_allowed_for_group_admin(monkeypatch):
    """群聊管理员：设档与 clear 别名清覆盖都放行并路由到 service。"""
    monkeypatch.setattr(llm_part, "_allow_scope_management", lambda event: True)

    finished, service = await _dispatch(monkeypatch, "/llm effort high", _FakeGroupEvent)
    assert service.calls == [("high", "group")]
    assert len(finished) == 1

    finished, service = await _dispatch(monkeypatch, "/llm effort clear", _FakeGroupEvent)
    assert service.calls == [(None, "group")]
    assert len(finished) == 1
