from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quickquip.adapters.nonebot import member_cards
from quickquip.adapters.nonebot._llm_reply import (
    build_llm_reply_message,
    split_outbound_at_mentions,
)
from quickquip.llm.identity import IdentityIndex
from quickquip.llm.prompting import build_turn_envelope
from quickquip.llm.rendering import render_message_for_llm
from quickquip.llm.service import LLMService
from quickquip.llm.vocab import VocabIndex
_IDENTITIES_YAML = """people:
  - canonical_name: 镜子
    qq_ids:
      - "10002"
    aliases:
      - 镜千翎
      - 哈基镜
    note: 特别注意不要和王者荣耀的镜混淆

  - canonical_name: 4s
    qq_ids: ["40004"]
    aliases: ["Туманность", "哈基四"]
    note: 大部分以四字开头的称呼通常指 4s
"""

TZ = ZoneInfo("Asia/Shanghai")


class _FakeSegment:
    @staticmethod
    def text(value: str):
        return ("text", value)

    @staticmethod
    def image(value: str):
        return ("image", value)

    @staticmethod
    def at(qq: int):
        return ("at", qq)


class _FakeMessage(list):
    def __init__(self, segments):
        super().__init__(segments)


class _Seg:
    def __init__(self, seg_type: str, data: dict):
        self.type = seg_type
        self.data = data


def _at(qq: str) -> _Seg:
    return _Seg("at", {"qq": qq})


def _text(value: str) -> _Seg:
    return _Seg("text", {"text": value})


# ── F1：加载日志 ─────────────────────────────────────────────────────


def test_from_file_missing_logs_info_and_returns_empty(tmp_path: Path, caplog):
    with caplog.at_level(logging.INFO, logger="quickquip.llm.identity"):
        index = IdentityIndex.from_file(tmp_path / "absent.yaml")
    assert index.entries == []
    assert any("不存在" in record.message for record in caplog.records)


def test_from_file_empty_template_logs_warning(tmp_path: Path, caplog):
    path = tmp_path / "identities.yaml"
    path.write_text(
        "people:\n  - canonical_name: \n    qq_ids:\n      - \"\"\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="quickquip.llm.identity"):
        index = IdentityIndex.from_file(path)
    assert index.entries == []
    assert any("无有效条目" in record.message for record in caplog.records)


def test_from_file_loaded_logs_count(tmp_path: Path, caplog):
    path = tmp_path / "identities.yaml"
    path.write_text(_IDENTITIES_YAML, encoding="utf-8")
    with caplog.at_level(logging.INFO, logger="quickquip.llm.identity"):
        index = IdentityIndex.from_file(path)
    assert len(index.entries) == 2
    assert any("已加载 2 条身份" in record.message for record in caplog.records)


# ── F2：@ 提及渲染（标准身份优先、未登记退化名片） ──────────────────


def _loaded_index(tmp_path: Path) -> IdentityIndex:
    path = tmp_path / "identities.yaml"
    path.write_text(_IDENTITIES_YAML, encoding="utf-8")
    return IdentityIndex.from_file(path)


def test_render_mention_registered_uses_canonical(tmp_path: Path):
    assert _loaded_index(tmp_path).render_mention("10002") == "@镜子"


def test_render_mention_unregistered_falls_back_to_card(tmp_path: Path):
    assert _loaded_index(tmp_path).render_mention("99999", fallback_name="路人甲") == "@路人甲"


def test_render_mention_unregistered_without_card_keeps_digits(tmp_path: Path):
    assert _loaded_index(tmp_path).render_mention("99999") == "@QQ99999"


def test_render_collects_mentioned_qq_ids_excluding_bot(tmp_path: Path):
    index = _loaded_index(tmp_path)
    message = [
        _at("10002"),
        _text(" 看看这个 "),
        _at("3003"),
        _at("3003"),
        _at("777"),
    ]
    rendered = render_message_for_llm(
        message,
        bot_self_ids={"777"},
        identity_index=index,
        mention_names={"3003": "小透明"},
    )
    assert rendered.mentioned_qq_ids == ["10002", "3003"]
    # 已登记 → 标准身份；未登记但有名片 → 名片；bot 自身 → 空段
    assert "@镜子" in rendered.text
    assert "@小透明" in rendered.text


# ── F3：信封档案注入 ────────────────────────────────────────────────


def _envelope(mention_profiles=None) -> str:
    return build_turn_envelope(
        now=datetime(2026, 9, 11, 12, 0, tzinfo=TZ),
        prompt="问题",
        memories=[],
        vocab=VocabIndex(),
        mention_profiles=mention_profiles,
    )


def test_envelope_omits_profile_section_when_empty():
    assert "被艾特" not in _envelope()
    assert "被艾特" not in _envelope(mention_profiles=[])


def test_envelope_renders_mention_profiles_name_first():
    envelope = _envelope(
        mention_profiles=[
            {
                "canonical_name": "4s",
                "user_id": "40004",
                "aliases": "哈基四、四*",
                "note": "大部分以四字开头的称呼通常指 4s",
            }
        ]
    )
    assert "以下成员在消息中被艾特但未在窗口内发言，档案按 QQ 号对应：" in envelope
    assert "- 4s（QQ 40004）：别名哈基四、四*；大部分以四字开头的称呼通常指 4s" in envelope


def test_envelope_profile_without_aliases_or_note_bare_label():
    envelope = _envelope(
        mention_profiles=[{"canonical_name": "镜子", "user_id": "10002", "aliases": "", "note": ""}]
    )
    assert "- 镜子（QQ 10002）" in envelope


# ── F3：_collect_mention_profiles（双路采集 + 过滤 + 上限） ──────────


def _bare_service(tmp_path: Path) -> LLMService:
    service = LLMService.__new__(LLMService)
    service.identity_path = tmp_path / "identities.yaml"
    service.identity_path.write_text(_IDENTITIES_YAML, encoding="utf-8")
    service.identities = IdentityIndex.from_file(service.identity_path)
    service._group_identities = OrderedDict()
    return service


def test_collect_mention_profiles_structured_and_regex(tmp_path: Path):
    service = _bare_service(tmp_path)
    profiles = service._collect_mention_profiles(
        chat_id="100",
        mentioned_qq_ids=["40004"],
        prompt="问一下 @QQ10002 是谁",
        quoted_text="",
        forward_text="",
        history=[{"user_id": "1111", "role": "user", "raw_content": "@QQ40004 也在吗"}],
        scene_patch=[{"user_id": "2222", "text": "路过"}],
        current_user_id="1111",
        quoted_user_id="",
    )
    # 40004 既被结构化提及也在历史正文出现 → 去重为一条；10002 未发言 → 注入；
    # 1111/2222 在窗口有标签 → 跳过
    assert [(p["canonical_name"], p["user_id"]) for p in profiles] == [
        ("4s", "40004"),
        ("镜子", "10002"),
    ]


def test_collect_mention_profiles_skips_speakers_and_unregistered(tmp_path: Path):
    service = _bare_service(tmp_path)
    profiles = service._collect_mention_profiles(
        chat_id="100",
        mentioned_qq_ids=["10002", "99999"],
        prompt="",
        quoted_text="",
        forward_text="",
        history=[{"user_id": "10002", "role": "user", "content": "我说过话"}],
        scene_patch=[],
        current_user_id="1111",
        quoted_user_id="",
    )
    # 10002 已发言（窗口有标签）；99999 未登记 → 均不注入
    assert profiles == []


def test_collect_mention_profiles_dedupes_candidates(tmp_path: Path):
    """结构化候选与正则命中去重：同一 QQ 只注入一条，按首次出现顺序。"""
    service = _bare_service(tmp_path)
    profiles = service._collect_mention_profiles(
        chat_id="100",
        mentioned_qq_ids=["40004", "40004", "10002"],
        prompt="@QQ40004",
        quoted_text="",
        forward_text="",
        history=[],
        scene_patch=[],
        current_user_id="11111",
        quoted_user_id="",
    )
    assert profiles == [
        {"canonical_name": "4s", "user_id": "40004", "aliases": "Туманность、哈基四", "note": "大部分以四字开头的称呼通常指 4s"},
        {"canonical_name": "镜子", "user_id": "10002", "aliases": "镜千翎、哈基镜", "note": "特别注意不要和王者荣耀的镜混淆"},
    ]


def test_collect_mention_profiles_caps_at_five(tmp_path: Path):
    """候选超过上限时只注入前 5 条（按首次出现顺序截断）。"""
    people = "\n".join(
        f'  - canonical_name: 成员{i}\n    qq_ids:\n      - "7{i:05d}"'
        for i in range(7)
    )
    path = tmp_path / "identities.yaml"
    path.write_text(f"people:\n{people}\n", encoding="utf-8")
    service = LLMService.__new__(LLMService)
    service.identity_path = path
    service.identities = IdentityIndex.from_file(path)
    service._group_identities = OrderedDict()

    profiles = service._collect_mention_profiles(
        chat_id="100",
        mentioned_qq_ids=[f"7{i:05d}" for i in range(7)],
        prompt="",
        quoted_text="",
        forward_text="",
        history=[],
        scene_patch=[],
        current_user_id="11111",
        quoted_user_id="",
    )
    assert [p["user_id"] for p in profiles] == [f"7{i:05d}" for i in range(5)]


# ── F3：出站 @QQ 数字 → at 段 ──────────────────────────────────────


def test_split_outbound_at_mentions_plain_text_untouched():
    segments = split_outbound_at_mentions("普通回复，无艾特", _FakeMessage, _FakeSegment)
    assert segments == [("text", "普通回复，无艾特")]


def test_split_outbound_at_mentions_converts_digits():
    segments = split_outbound_at_mentions(
        "@QQ40004 的话没有档案，@QQ10002 可以", _FakeMessage, _FakeSegment
    )
    assert segments == [
        ("at", 40004),
        ("text", " 的话没有档案，"),
        ("at", 10002),
        ("text", " 可以"),
    ]


def test_build_llm_reply_message_splits_at_mentions():
    message = build_llm_reply_message(
        {"reply": "提醒 @QQ40004 看一下", "images": []}, _FakeMessage, _FakeSegment
    )
    assert list(message) == [
        ("text", "提醒 "),
        ("at", 40004),
        ("text", " 看一下"),
    ]


# ── F2：成员名片缓存 ────────────────────────────────────────────────


class _FakeBot:
    def __init__(self, cards: dict[str, str] | None = None, fail_qqs: set[str] | None = None):
        self.cards = cards or {}
        self.fail_qqs = fail_qqs or set()
        self.calls: list[str] = []

    async def get_group_member_info(self, *, group_id: int, user_id: int):
        self.calls.append(str(user_id))
        if str(user_id) in self.fail_qqs:
            raise RuntimeError("api down")
        return {"card": self.cards.get(str(user_id), "")}


@pytest.mark.asyncio
async def test_fetch_mention_names_skips_registered_and_uses_cache():
    member_cards.reset_member_card_cache()
    bot = _FakeBot(cards={"3003": "小透明"})

    names = await member_cards.fetch_mention_names(
        bot, 100, ["10002", "3003"], is_registered=lambda qq: qq == "10002"
    )
    assert names == {"3003": "小透明"}
    assert bot.calls == ["3003"]

    # 第二次命中缓存，不再请求协议端
    await member_cards.fetch_mention_names(
        bot, 100, ["3003"], is_registered=lambda qq: False
    )
    assert bot.calls == ["3003"]


@pytest.mark.asyncio
async def test_fetch_mention_names_tolerates_api_failure():
    member_cards.reset_member_card_cache()
    bot = _FakeBot(fail_qqs={"3003"})
    names = await member_cards.fetch_mention_names(
        bot, 100, ["3003"], is_registered=lambda qq: False
    )
    assert names == {}
