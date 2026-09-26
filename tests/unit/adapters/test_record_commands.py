from types import SimpleNamespace

from nonebot.adapters.onebot.v11 import Message, MessageSegment
import pytest

from quickquip.adapters.nonebot.command_parts import history, memory
from quickquip.app.identities import IdentitySnapshot, identities
from quickquip.common.identity import IdentityEntry, IdentityIndex
from quickquip.chat.group_quotes import GroupQuoteStore
from quickquip.llm.store import LLMStore


class Finished(Exception):
    pass


class Matcher:
    def __init__(self):
        self.handlers = []
        self.sent = []

    def handle(self):
        def register(fn):
            self.handlers.append(fn)
            return fn
        return register

    async def finish(self, message):
        self.sent.append(message)
        raise Finished


def register(fn):
    matchers = {}
    def command(name, **kwargs):
        matchers[name] = Matcher()
        return matchers[name]
    fn(command, Message, MessageSegment)
    return matchers


@pytest.fixture
def snapshot(monkeypatch):
    index = IdentityIndex(entries=[IdentityEntry("标准名", ["12345"], [], "")])
    index._build_indexes()
    snapshot = IdentitySnapshot(index, {})
    monkeypatch.setattr(identities, "snapshot", lambda scope: snapshot)
    return snapshot


async def test_screenshot_remember_and_literal_cq(tmp_path, monkeypatch, snapshot):
    store = LLMStore(tmp_path / "llm.db")
    svc = SimpleNamespace(
        remember_memory=lambda group, content, **kw: store.add_memory(
            group, content, content_parts=kw["content_parts"]
        )
    )
    monkeypatch.setattr(memory, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(memory, "get_llm_service", lambda: svc)
    monkeypatch.setattr(memory, "_allow_scope_management", lambda event: True)
    message = Message(
        [MessageSegment.text("/remember "),
         MessageSegment("at", {"qq": "12345", "name": "旧名"}),
         MessageSegment.text(" 喜欢编程")]
    )
    event = SimpleNamespace(
        group_id=10001, user_id=99999, message_type="group", get_message=lambda: message
    )
    matcher = register(memory.register_memory_commands)["remember"]
    with pytest.raises(Finished):
        await matcher.handlers[0](event)
    row = store.list_memories(10001)[0]
    assert row["scope"] == "group" and row["user_id"] is None
    assert row["content_display"] == "@标准名 喜欢编程"
    assert "[CQ:" not in row["content_display"]


async def test_screenshot_quote_name_fallback_and_command_retained(tmp_path, monkeypatch, snapshot):
    store = GroupQuoteStore(tmp_path / "quotes.db")
    monkeypatch.setattr(history, "group_quote_store", store)
    monkeypatch.setattr(
        history, "get_sender_identity_sources", lambda scope: (snapshot.names, snapshot.index)
    )
    reply = SimpleNamespace(
        user_id="12345", sender=SimpleNamespace(nickname="旧作者", card=""),
        message="/remember [CQ:at,name=可用名称,qq=23456,extra=ok] [CQ:image,file=x]"
    )
    event = SimpleNamespace(
        group_id=10001, user_id=99999, self_id=88888, message_type="group",
        reply=reply, get_message=lambda: Message("/quote"),
    )
    matcher = register(history.register_history_commands)["quote"]
    with pytest.raises(Finished):
        await matcher.handlers[0](event)
    row = store.get_by_seq(10001, 1)
    assert row["content_display"] == "/remember @可用名称 [图片]"
    assert "@QQ23456" not in str(matcher.sent[-1])
    # Literal CQ inside a new text segment is sent as text on historical reads.
    reply.message = Message([MessageSegment.text("[CQ:at,qq=23456]")])
    with pytest.raises(Finished):
        await matcher.handlers[0](event)
    event.reply = None
    event.get_message = lambda: Message("/quote 2")
    with pytest.raises(Finished):
        await matcher.handlers[0](event)
    segment = matcher.sent[-1]
    assert segment.type == "text"
    assert "[CQ:at,qq=23456]" in segment.data["text"]
    store.close()


async def test_quote_pure_media_rejected(tmp_path, monkeypatch, snapshot):
    store = GroupQuoteStore(tmp_path / "quotes.db")
    monkeypatch.setattr(history, "group_quote_store", store)
    event = SimpleNamespace(
        group_id=10001, user_id=99999, message_type="group",
        reply=SimpleNamespace(user_id="12345", message="[CQ:image,file=x]"),
        get_message=lambda: Message("/quote"),
    )
    matcher = register(history.register_history_commands)["quote"]
    with pytest.raises(Finished):
        await matcher.handlers[0](event)
    assert store.count(10001) == 0
    store.close()


async def test_quote_trailing_whitespace_limit_returns_feedback(tmp_path, monkeypatch, snapshot):
    store = GroupQuoteStore(tmp_path / "quotes.db")
    monkeypatch.setattr(history, "group_quote_store", store)
    event = SimpleNamespace(
        group_id=10001, user_id=99999, message_type="group",
        reply=SimpleNamespace(user_id="12345", message="字" * 500 + " " * 5),
        get_message=lambda: Message("/quote"),
    )
    matcher = register(history.register_history_commands)["quote"]
    with pytest.raises(Finished):
        await matcher.handlers[0](event)
    assert "内容过长" in matcher.sent[-1].data["text"]
    assert store.count(10001) == 0
    store.close()


async def test_find_filters_in_worker_and_resolves_author(monkeypatch, snapshot):
    import threading
    main_thread = threading.get_ident()
    worker_threads = []
    original = history._find_hits
    def filter_in_thread(*args):
        worker_threads.append(threading.get_ident())
        return original(*args)
    monkeypatch.setattr(history, "_find_hits", filter_in_thread)
    monkeypatch.setattr(history, "chat_archive", SimpleNamespace(read_window=lambda *args: [
        {"user_id": "12345", "sender": "旧名", "text": "普通发言", "ts": 1},
        {"user_id": "23456", "sender": "某人", "text": "[CQ:at,qq=12345]", "ts": 2},
    ]))
    event = SimpleNamespace(
        group_id=10001, user_id=99999, message_type="group",
        get_message=lambda: Message("/find 标准名"),
    )
    matcher = register(history.register_history_commands)["find"]
    with pytest.raises(Finished):
        await matcher.handlers[0](event)
    assert worker_threads and worker_threads[0] != main_thread
    text = matcher.sent[-1].data["text"]
    assert "找到 2 条" in text and "标准名: 普通发言" in text and "@标准名" in text
