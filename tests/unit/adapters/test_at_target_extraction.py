"""_extract_at_target 的回归测试。

历史事故：基座从 NapCat 换成 LLOneBot 后，at CQ 码多了 name= 扩展键，
旧正则只认裸 ``qq=数字]`` 形态导致 @ 提取全部失配；叠加 NoneBot 会把
指向 bot 自身的 at 段从 get_message() 剥掉，「跟机器人击剑」两层提取
同时失效，永远回复"你要和谁击剑？请 @一位用户"。
"""

from __future__ import annotations

from quickquip.adapters.nonebot.command_parts._parsing import _extract_at_target


class _Seg:
    def __init__(self, type: str, **data):  # noqa: A002
        self.type = type
        self.data = data


def test_raw_with_name_field_extracts_target():
    """LLOneBot 形态：at 码带 name= 扩展键。"""
    raw = "/击剑[CQ:at,qq=2315478846,name=Mon3tr「哈基米显现」] "
    assert _extract_at_target(raw, ()) == "2315478846"


def test_raw_bare_form_extracts_target():
    """NapCat 形态：裸 qq= 数字紧接收尾括号。"""
    assert _extract_at_target("/击剑[CQ:at,qq=2740766318]", ()) == "2740766318"


def test_self_at_survives_stripped_segments():
    """self-@ 场景：段被 to_me 剥掉，仅 raw_message 保留 at 码。"""
    raw = "/击剑[CQ:at,qq=2315478846,name=Bot] "
    assert _extract_at_target(raw, []) == "2315478846"


def test_segments_fallback_when_raw_lacks_at():
    """raw 无 at 时回退段解析。"""
    segs = [_Seg("text", text="hi"), _Seg("at", qq="123456789")]
    assert _extract_at_target("没有艾特", segs) == "123456789"


def test_at_all_is_not_a_target():
    """@全体不视为目标（raw 与段两条路径都不认）。"""
    assert _extract_at_target("/击剑[CQ:at,qq=all]", ()) is None
    assert _extract_at_target(None, [_Seg("at", qq="all")]) is None


def test_no_target_anywhere_returns_none():
    assert _extract_at_target("普通消息", [_Seg("text", text="普通消息")]) is None
    assert _extract_at_target("", ()) is None
    assert _extract_at_target(None, ()) is None


def test_raw_takes_precedence_over_segments():
    raw = "/击剑[CQ:at,qq=111111111] "
    segs = [_Seg("at", qq="222222222")]
    assert _extract_at_target(raw, segs) == "111111111"
