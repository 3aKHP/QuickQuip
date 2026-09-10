"""`/llm delivery` 三域子命令的解析与写入路由（两域独立开关）。

域 token 与配置/存储同词根（intermediate/final/all，DeliveryDomain 枚举）；
覆盖 on/off/reset/status 与无域概览；不合法输入不得触发任何写入。
"""
from __future__ import annotations

import types

import pytest

from quickquip.adapters.nonebot.command_parts import llm as llm_part
from quickquip.llm.settings import DeliveryDomain


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
    """私聊事件：绕过管理员判定，聚焦 delivery 子命令分支。"""

    def __init__(self, text: str) -> None:
        self._text = text
        self.message_type = "private"
        self.user_id = 2002
        self.group_id = None

    def get_message(self) -> str:
        return self._text


class _FakeRuntime:
    def __init__(self) -> None:
        self.agent_delivery_intermediate_enabled = False
        self.agent_delivery_final_enabled = False


class _FakeSettings:
    def __init__(self, intermediate: bool, final: bool) -> None:
        self.agent_delivery_intermediate_enabled = intermediate
        self.agent_delivery_final_enabled = final


class _FakeService:
    def __init__(self) -> None:
        self.config = types.SimpleNamespace(runtime=_FakeRuntime())
        self.settings = _FakeSettings(False, False)
        self.calls: list[tuple[object, str, DeliveryDomain]] = []

    def get_chat_settings(self, chat_id, chat_type: str = "group"):
        return self.settings

    def set_chat_agent_delivery_enabled(
        self, chat_id, enabled, chat_type: str = "group", domain: DeliveryDomain = DeliveryDomain.ALL
    ) -> None:
        self.calls.append((enabled, chat_type, domain))


_SEG = type("Seg", (), {
    "text": staticmethod(lambda v: v),
    "image": staticmethod(lambda v: v),
    "record": staticmethod(lambda v: v),
})


def _register(service) -> _FakeLlmCmd:
    cmd = _FakeLlmCmd()
    llm_part.register_llm_commands(lambda name, **kw: (cmd if name == "llm" else _FakeLlmCmd()), list, _SEG)
    return cmd


def _patch_service(monkeypatch: pytest.MonkeyPatch, service: _FakeService) -> None:
    monkeypatch.setattr(llm_part, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(llm_part, "get_llm_service", lambda: service)


async def _dispatch(monkeypatch, text: str) -> tuple[list[str], _FakeService]:
    service = _FakeService()
    _patch_service(monkeypatch, service)
    cmd = _register(service)
    with pytest.raises(_FinishSentinel):
        await cmd.handler(_FakeEvent(text))
    return cmd.finished, service


async def test_delivery_domain_actions_route_to_service(monkeypatch):
    """on/off/reset 按域写入：intermediate/final 单域，all 双域。"""
    _, service = await _dispatch(monkeypatch, "/llm delivery intermediate on")
    assert service.calls == [(True, "private", DeliveryDomain.INTERMEDIATE)]

    _, service = await _dispatch(monkeypatch, "/llm delivery final off")
    assert service.calls == [(False, "private", DeliveryDomain.FINAL)]

    _, service = await _dispatch(monkeypatch, "/llm delivery all reset")
    assert service.calls == [(None, "private", DeliveryDomain.ALL)]


async def test_delivery_status_outputs(monkeypatch):
    """带域 status 单行；无域 status 两域概览；all status 等同概览。"""
    service = _FakeService()
    service.settings = _FakeSettings(True, False)
    _patch_service(monkeypatch, service)

    cmd = _register(service)
    with pytest.raises(_FinishSentinel):
        await cmd.handler(_FakeEvent("/llm delivery final status"))
    assert cmd.finished == ["当前私聊最终轮分段：关（全局默认 关）"]

    cmd2 = _register(service)
    with pytest.raises(_FinishSentinel):
        await cmd2.handler(_FakeEvent("/llm delivery"))
    assert cmd2.finished == [
        "当前私聊分段交付：中间轮 开（默认 关） / 最终轮 关（默认 关）"
    ]

    cmd3 = _register(service)
    with pytest.raises(_FinishSentinel):
        await cmd3.handler(_FakeEvent("/llm delivery all status"))
    assert cmd3.finished == cmd2.finished


async def test_delivery_unknown_domain_is_noop(monkeypatch):
    """不认识的域/动作只落用法提示，不触发任何写入。"""
    service = _FakeService()
    _patch_service(monkeypatch, service)
    cmd = _register(service)
    with pytest.raises(_FinishSentinel):
        await cmd.handler(_FakeEvent("/llm delivery xyz on"))
    with pytest.raises(_FinishSentinel):
        await cmd.handler(_FakeEvent("/llm delivery intermediate maybe"))
    assert service.calls == []
    assert len(cmd.finished) == 2
    assert all("用法" in msg for msg in cmd.finished)
