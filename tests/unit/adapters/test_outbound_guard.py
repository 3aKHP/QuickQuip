from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from quickquip.adapters.nonebot.outbound_guard import (
    guard_outbound_api_call,
    install_nonebot_outbound_guard,
)
from quickquip.common.sensitive_filter import DEFAULT_OUTPUT_FALLBACK, SensitiveFilter
from tests.fixtures.sensitive_filter import make_sensitive_filter


@dataclass
class _Seg:
    type: str
    data: dict[str, Any]


class _FakeBot:
    self_id = "1000000000"


def test_guard_noop_when_filter_unloaded():
    sf = SensitiveFilter.empty()
    data = {"group_id": 123456, "message": "任何内容"}
    assert guard_outbound_api_call(_FakeBot(), "send_group_msg", data, sensitive_filter=sf) is False
    assert data["message"] == "任何内容"


def test_guard_ignores_non_send_apis(tmp_path: Path):
    sf = make_sensitive_filter(tmp_path, "block", "违禁词")
    data = {"group_id": 123456, "message": "违禁词"}
    assert guard_outbound_api_call(_FakeBot(), "get_group_info", data, sensitive_filter=sf) is False
    assert data["message"] == "违禁词"


@pytest.mark.parametrize("api", ["send_msg", "send_group_msg", "send_private_msg"])
def test_guard_blocks_all_single_message_shapes_without_mutating_caller_objects(
    tmp_path: Path, api: str
):
    sf = make_sensitive_filter(tmp_path, "block", "违禁词")

    # 1. str
    d_str = {"group_id": 123456, "message": "包含违禁词的消息"}
    assert guard_outbound_api_call(_FakeBot(), api, d_str, sensitive_filter=sf) is True
    assert d_str["message"] == [{"type": "text", "data": {"text": DEFAULT_OUTPUT_FALLBACK}}]

    # 2. single MessageSegment
    seg = _Seg("text", {"text": "含违禁词"})
    d_seg = {"user_id": 1000000001, "message": seg}
    assert guard_outbound_api_call(_FakeBot(), api, d_seg, sensitive_filter=sf) is True
    assert seg.data["text"] == "含违禁词"  # caller object untouched
    assert d_seg["message"] == [{"type": "text", "data": {"text": DEFAULT_OUTPUT_FALLBACK}}]

    # 3. list[dict] with split text segments across boundaries
    orig_list = [
        {"type": "text", "data": {"text": "违"}},
        {"type": "text", "data": {"text": "禁词"}},
        {"type": "image", "data": {"file": "base64://abc"}},
    ]
    d_list = {"group_id": 123456, "message": orig_list}
    assert guard_outbound_api_call(_FakeBot(), api, d_list, sensitive_filter=sf) is True
    assert orig_list[0]["data"]["text"] == "违"  # caller list untouched
    assert d_list["message"] == [{"type": "text", "data": {"text": DEFAULT_OUTPUT_FALLBACK}}]


def test_guard_does_not_scan_non_text_segment_attributes(tmp_path: Path):
    sf = make_sensitive_filter(tmp_path, "block", "secret")
    data = {
        "group_id": 123456,
        "message": [
            {"type": "image", "data": {"file": "https://example.com/secret.png"}},
            {"type": "at", "data": {"qq": "1000000001"}},
            {"type": "text", "data": {"text": "正常文本"}},
        ],
    }
    assert guard_outbound_api_call(_FakeBot(), "send_group_msg", data, sensitive_filter=sf) is False


def test_guard_soft_hits_log_but_pass_through(tmp_path: Path, caplog):
    sf = make_sensitive_filter(tmp_path, "soft", "擦边词")
    data = {"group_id": 123456, "message": "包含擦边词"}
    with caplog.at_level("INFO", logger="quickquip.common.sensitive_filter"):
        blocked = guard_outbound_api_call(
            _FakeBot(), "send_group_msg", data, sensitive_filter=sf
        )
    assert blocked is False
    assert data["message"] == "包含擦边词"
    assert "outbound_api:send_group_msg" in caplog.text
    assert "擦边词" not in caplog.text


@pytest.mark.parametrize("api", ["send_group_forward_msg", "send_private_forward_msg"])
def test_guard_blocks_nested_forward_nodes_and_preserves_sender_meta(tmp_path: Path, api: str):
    sf = make_sensitive_filter(tmp_path, "block", "违禁词")
    orig_nodes = [
        {
            "type": "node",
            "data": {
                "name": "日报小助手",
                "uin": "1000000002",
                "content": [
                    {
                        "type": "node",
                        "data": {
                            "name": "嵌套节点",
                            "uin": "1000000003",
                            "content": [{"type": "text", "data": {"text": "深层违禁词"}}],
                        },
                    }
                ],
            },
        }
    ]
    data = {"group_id": 123456, "messages": orig_nodes}
    assert guard_outbound_api_call(_FakeBot(), api, data, sensitive_filter=sf) is True
    # Original node untouched
    assert orig_nodes[0]["data"]["content"][0]["data"]["content"][0]["data"]["text"] == "深层违禁词"
    assert data["messages"] == [
        {
            "type": "node",
            "data": {
                "name": "日报小助手",
                "uin": "1000000002",
                "content": [{"type": "text", "data": {"text": DEFAULT_OUTPUT_FALLBACK}}],
            },
        }
    ]


@pytest.mark.asyncio
async def test_install_nonebot_outbound_guard_idempotent(tmp_path: Path, monkeypatch):
    sf = make_sensitive_filter(tmp_path, "block", "违禁词")
    monkeypatch.setattr("quickquip.adapters.nonebot.outbound_guard.get_filter", lambda: sf)

    class _LocalBot:
        self_id = "1000000000"
        hooks: list[Any] = []

        @classmethod
        def on_calling_api(cls, fn):
            cls.hooks.append(fn)
            return fn

    assert install_nonebot_outbound_guard(_LocalBot) is True
    assert install_nonebot_outbound_guard(_LocalBot) is False
    assert len(_LocalBot.hooks) == 1

    payload = {"group_id": 123456, "message": "含违禁词"}
    await _LocalBot.hooks[0](_LocalBot(), "send_group_msg", payload)
    assert payload["message"] == [{"type": "text", "data": {"text": DEFAULT_OUTPUT_FALLBACK}}]


def test_guard_real_onebot_message_not_mutated(tmp_path: Path):
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    sf = make_sensitive_filter(tmp_path, "block", "违禁词")
    msg = Message([MessageSegment.text("包含违禁词")])
    data = {"group_id": 123456, "message": msg}
    assert guard_outbound_api_call(_FakeBot(), "send_group_msg", data, sensitive_filter=sf) is True
    assert str(msg) == "包含违禁词"
    assert data["message"] == [{"type": "text", "data": {"text": DEFAULT_OUTPUT_FALLBACK}}]


def test_guard_fails_closed_on_malformed_segment(tmp_path: Path):
    sf = make_sensitive_filter(tmp_path, "block", "违禁词")

    class _ExplodingSeg:
        @property
        def type(self):
            raise RuntimeError("boom")

    data = {"group_id": 123456, "message": _ExplodingSeg()}
    assert guard_outbound_api_call(_FakeBot(), "send_group_msg", data, sensitive_filter=sf) is True
    assert data["message"] == [{"type": "text", "data": {"text": DEFAULT_OUTPUT_FALLBACK}}]

    fwd = {"group_id": 123456, "messages": [_ExplodingSeg()]}
    assert (
        guard_outbound_api_call(_FakeBot(), "send_group_forward_msg", fwd, sensitive_filter=sf)
        is True
    )
    assert fwd["messages"][0]["data"]["content"] == [
        {"type": "text", "data": {"text": DEFAULT_OUTPUT_FALLBACK}}
    ]
