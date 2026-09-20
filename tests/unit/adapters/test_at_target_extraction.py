"""_extract_at_target 的回归测试。

历史事故：基座从 NapCat 换成 LLOneBot 后，at CQ 码多了 name= 扩展键，
旧正则只认裸 ``qq=数字]`` 形态导致 @ 提取全部失配；叠加 NoneBot 会把
指向 bot 自身的 at 段从 get_message() 剥掉，「跟机器人击剑」两层提取
同时失效，永远回复"你要和谁击剑？请 @一位用户"。
"""

from __future__ import annotations

from quickquip.adapters.nonebot.command_parts._parsing import (
    _extract_at_target,
    _raw_message_text,
)


class _Seg:
    def __init__(self, type: str, **data):
        self.type = type
        self.data = data


class _Event:
    def __init__(self, raw_message, message):
        self.raw_message = raw_message
        self._message = message

    def get_message(self):
        return self._message


def test_raw_message_text_prefers_raw():
    event = _Event("/击剑[CQ:at,qq=123456789]", [_Seg("at", qq="987654321")])
    assert _raw_message_text(event) == "/击剑[CQ:at,qq=123456789]"


def test_raw_message_text_falls_back_to_segment_serialization():
    for empty in (None, ""):
        event = _Event(empty, [_Seg("at", qq="987654321")])
        assert _raw_message_text(event) == str(event.get_message())


def test_raw_with_name_field_extracts_target():
    """LLOneBot 形态：at 码带 name= 扩展键。"""
    raw = "/击剑[CQ:at,qq=1000000000,name=Mon3tr「哈基米显现」] "
    assert _extract_at_target(raw, ()) == "1000000000"


def test_raw_bare_form_extracts_target():
    """NapCat 形态：裸 qq= 数字紧接收尾括号。"""
    assert _extract_at_target("/击剑[CQ:at,qq=123456789]", ()) == "123456789"


def test_self_at_survives_stripped_segments():
    """self-@ 场景：段被 to_me 剥空，raw_message 回退保住 bot 目标。"""
    raw = "/击剑[CQ:at,qq=1000000000,name=Bot] "
    assert _extract_at_target(raw, []) == "1000000000"


def test_segments_take_precedence_over_raw():
    """@bot 前导唤起 + @他人指定目标：段里剩他人（self-@ 已被剥），
    raw 的首个 at 是 bot 自己——必须取段的他人。"""
    raw = "[CQ:at,qq=1000000000] /profile[CQ:at,qq=123456789]"
    segs = [_Seg("at", qq="123456789")]
    assert _extract_at_target(raw, segs) == "123456789"


def test_segments_fallback_when_raw_lacks_at():
    """raw 无 at 时同样走段解析。"""
    segs = [_Seg("text", text="hi"), _Seg("at", qq="123456789")]
    assert _extract_at_target("没有艾特", segs) == "123456789"


def test_first_at_in_raw_wins_for_multi_mention():
    """多 @ 取第一个：防守方 CD 按目标扣锁，选谁影响游戏公平。"""
    raw = "/击剑[CQ:at,qq=123456789,name=A][CQ:at,qq=987654321,name=B]"
    assert _extract_at_target(raw, ()) == "123456789"


def test_first_at_segment_wins_for_multi_mention():
    segs = [_Seg("at", qq="123456789"), _Seg("at", qq="987654321")]
    assert _extract_at_target(None, segs) == "123456789"


def test_at_all_skipped_in_favor_of_real_target():
    """@全体与 @真人混排时跳过 all，取真人。"""
    assert _extract_at_target("/击剑[CQ:at,qq=all][CQ:at,qq=123456789]", ()) == "123456789"
    segs = [_Seg("at", qq="all"), _Seg("at", qq="123456789")]
    assert _extract_at_target(None, segs) == "123456789"


def test_at_all_is_not_a_target():
    """仅 @全体不视为目标（raw 与段两条路径都不认）。"""
    assert _extract_at_target("/击剑[CQ:at,qq=all]", ()) is None
    assert _extract_at_target(None, [_Seg("at", qq="all")]) is None


def test_no_target_anywhere_returns_none():
    assert _extract_at_target("普通消息", [_Seg("text", text="普通消息")]) is None
    assert _extract_at_target("", ()) is None
    assert _extract_at_target(None, ()) is None
