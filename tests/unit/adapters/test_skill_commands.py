"""/skill 命令解析与路由（只读 list 子命令）。"""
from __future__ import annotations

import pytest

from quickquip.adapters.nonebot.command_parts import skills as skills_part


class _FinishSentinel(Exception):
    """模拟 nonebot finish() 终止 handler。"""


class _FakeSkillCmd:
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


class _FakeGroupEvent:
    def __init__(self, text: str) -> None:
        self._text = text
        self.message_type = "group"
        self.user_id = 2002
        self.group_id = 1001

    def get_message(self) -> str:
        return self._text


class _FakePrivateEvent(_FakeGroupEvent):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.message_type = "private"
        self.group_id = None


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str]] = []

    def format_skill_list(self, chat_id, chat_type: str = "group") -> str:
        self.calls.append((chat_id, chat_type))
        return f"LIST[{chat_type}:{chat_id}]"


_SEG = type("Seg", (), {"text": staticmethod(lambda v: v)})


def _register() -> _FakeSkillCmd:
    cmd = _FakeSkillCmd()
    skills_part.register_skills_commands(
        lambda name, **kw: (cmd if name == "skill" else _FakeSkillCmd()), list, _SEG
    )
    return cmd


def _patch_service(monkeypatch: pytest.MonkeyPatch, service: _FakeService) -> None:
    monkeypatch.setattr(skills_part, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(skills_part, "get_llm_service", lambda: service)


async def _dispatch(monkeypatch, event) -> tuple[list[str], _FakeService]:
    service = _FakeService()
    _patch_service(monkeypatch, service)
    cmd = _register()
    with pytest.raises(_FinishSentinel):
        await cmd.handler(event)
    return cmd.finished, service


async def test_skill_list_group_routes_scope(monkeypatch):
    finished, service = await _dispatch(monkeypatch, _FakeGroupEvent("/skill list"))
    assert service.calls == [(1001, "group")]
    assert finished == ["LIST[group:1001]"]


async def test_skill_list_private_routes_scope(monkeypatch):
    finished, service = await _dispatch(monkeypatch, _FakePrivateEvent("/skill list"))
    assert service.calls == [(2002, "private")]
    assert finished == ["LIST[private:2002]"]


async def test_skill_bare_and_unknown_subcommand_show_usage(monkeypatch):
    for text in ("/skill", "/skill use demo", "/skill activate demo"):
        finished, service = await _dispatch(monkeypatch, _FakeGroupEvent(text))
        assert len(finished) == 1 and "用法" in finished[0], text
        assert service.calls == []  # 只读面之外一律不触服务
