import random
from datetime import datetime, time
from zoneinfo import ZoneInfo
from pathlib import Path
import shutil

from plugins.chain_game import ChainGameDef, ChainGameManager
from plugins.good_girl_chain import GoodGirlChainManager
from plugins.message_stats import GroupStatsTracker
from plugins.rate_limit import KeyedRateLimiter, SlidingWindowRateLimiter
from plugins.repeat_detector import GroupRepeatDetector
from plugins.rule_switch import GroupRuleSwitch
from plugins.text_reply_rules import match_text_rule, select_reply_template
from plugins.tz_tracker import (
    build_reply,
    build_timezone_reply,
    detect_kind,
    resolve_reply,
    rule_switch as global_rule_switch,
)
from plugins.tz_utils import (
    circular_diff_minutes,
    find_best_timezones,
    format_city_zh,
    format_location_zh,
)

fixed_now = datetime(2026, 3, 16, 9, 19, tzinfo=ZoneInfo("Asia/Shanghai"))

# 测试关键词检测
assert detect_kind("早安") == "wake"
assert detect_kind("晚安") == "sleep"
assert detect_kind("你好") is None

# 测试中文地点格式化
assert format_location_zh("Asia/Shanghai") == "亚洲/上海"
assert format_location_zh("Atlantic/Cape_Verde") == "大西洋/佛得角"
assert format_city_zh("Asia/Shanghai") == "上海"
assert format_city_zh("Atlantic/Cape_Verde") == "佛得角"

# 测试候选时区查找
candidates = find_best_timezones(fixed_now, time(7, 30), limit=3)
assert len(candidates) == 3
assert all("location_zh" in item for item in candidates)
assert all("city_zh" in item for item in candidates)
assert all("local_dt" in item for item in candidates)
assert all("diff" in item for item in candidates)
assert candidates[0]["diff"] <= candidates[1]["diff"] <= candidates[2]["diff"]
assert len({item["city_zh"] for item in candidates}) == 3

# 测试时区回复生成
reply_info = build_timezone_reply("早安", sender_name="测试用户", now=fixed_now)
reply = reply_info["reply"]
print(reply)
assert reply_info["rate_limit_key"] == "timezone_wake"
assert reply is not None
assert "现在是北京时间2026-03-16 09:19" in reply
assert "@测试用户 " in reply
assert "要起床了" in reply
assert "TA也有可能在" in reply

reply_info_2 = build_timezone_reply("晚安", sender_name="测试用户", now=fixed_now)
reply2 = reply_info_2["reply"]
print(reply2)
assert reply_info_2["rate_limit_key"] == "timezone_sleep"
assert reply2 is not None
assert "@测试用户 " in reply2
assert "要睡觉了" in reply2
assert "TA也有可能在" in reply2

# 测试彩蛋规则回复：应使用昵称而不是 QQ 号
special_match = match_text_rule("神临", user_id=123456, sender_name="测试用户", now=fixed_now)
special_reply = special_match["reply"]
print(special_reply)
assert special_match["rule_name"] == "divine_arrival"
assert special_match["rate_limit_key"] == "divine_arrival"
assert special_reply == "2026-03-16 09:19，@测试用户 区从天降"

special_match_2 = match_text_rule("他要降临了吗", user_id=123456, sender_name="测试用户", now=fixed_now)
assert special_match_2["reply"] == "2026-03-16 09:19，@测试用户 区从天降"

# 测试正则捕获公式化回复
regex_match = match_text_rule("玩原神玩的", user_id=123456, sender_name="测试用户", now=fixed_now)
regex_reply = regex_match["reply"]
print(regex_reply)
assert regex_match["rule_name"] == "play_target"
assert regex_match["rate_limit_key"] == "play_target"
assert regex_reply == "原神怎么你了"

# 测试规则优先级：同一句同时命中多个规则时，选择 priority 更高者
priority_match_1 = match_text_rule("神临，启动！", user_id=123456, sender_name="测试用户", now=fixed_now)
assert priority_match_1 is not None
assert priority_match_1["rule_name"] == "divine_arrival"
assert priority_match_1["priority"] == 100
assert priority_match_1["reply"] == "2026-03-16 09:19，@测试用户 区从天降"

priority_match_2 = match_text_rule("区来了，启动！", user_id=123456, sender_name="测试用户", now=fixed_now)
assert priority_match_2 is not None
assert priority_match_2["priority"] > 90

# 测试总回复分发：规则优先于作息时区回复
mixed_result = resolve_reply("神临早安", user_id=123456, sender_name="测试用户", now=fixed_now)
assert mixed_result["reply"] == "2026-03-16 09:19，@测试用户 区从天降"
assert mixed_result["rate_limit_key"] == "divine_arrival"

normal_result = resolve_reply("早安", user_id=123456, sender_name="测试用户", now=fixed_now)
assert normal_result is not None
assert normal_result["rate_limit_key"] == "timezone_wake"
assert "@测试用户 " in normal_result["reply"]
assert "要起床了" in normal_result["reply"]

normal_reply = build_reply("早安", user_id=123456, sender_name="测试用户", now=fixed_now)
assert normal_reply is not None
assert "@测试用户 " in normal_reply

# 测试新增正则词条
rule_reply_1 = match_text_rule("牛牛你的", user_id=123456, sender_name="测试用户", now=fixed_now)
assert rule_reply_1 is not None
assert rule_reply_1["rule_name"] == "double_char_ni_de"
assert rule_reply_1["rate_limit_key"] == "double_char_ni_de"
assert rule_reply_1["reply"] == "牛牛魔"

rule_reply_2 = match_text_rule("冰红茶冰的", user_id=123456, sender_name="测试用户", now=fixed_now)
assert rule_reply_2 is not None
assert rule_reply_2["rule_name"] == "sandwich_de"
assert rule_reply_2["rate_limit_key"] == "sandwich_de"
assert rule_reply_2["reply"] == "红茶怎么你了！"

rule_reply_3 = match_text_rule("我喜欢苹果", user_id=123456, sender_name="测试用户", now=fixed_now)
assert rule_reply_3 is not None
assert rule_reply_3["rule_name"] == "like_reply"
assert rule_reply_3["rate_limit_key"] == "like_reply"
assert rule_reply_3["reply"].startswith("还在")
assert match_text_rule("你喜欢苹果", user_id=123456, sender_name="测试用户", now=fixed_now) is None

rule_reply_4 = match_text_rule("我闭嘴", user_id=123456, sender_name="测试用户", now=fixed_now)
assert rule_reply_4 is not None
assert rule_reply_4["rule_name"] == "i_do"
assert rule_reply_4["reply"] == "不准闭嘴"
assert match_text_rule("我知道", user_id=123456, sender_name="测试用户", now=fixed_now) is None
assert match_text_rule("我觉得", user_id=123456, sender_name="测试用户", now=fixed_now) is None

# 无关消息不回复
assert build_reply("今天天气不错", user_id=123456, sender_name="测试用户", now=fixed_now) is None
assert resolve_reply("今天天气不错", user_id=123456, sender_name="测试用户", now=fixed_now) is None

# 测试旧限流器仍可单独工作
limiter = SlidingWindowRateLimiter(global_limit=4, user_limit=2, window_seconds=60)
assert limiter.allow("u1", now_ts=0) is True
assert limiter.allow("u1", now_ts=10) is True
assert limiter.allow("u1", now_ts=20) is False
assert limiter.allow("u1", now_ts=61) is True

# 测试分规则限流：不同 key 互不影响
keyed_limiter = KeyedRateLimiter(
    rule_limits={
        "timezone_wake": {"global_limit": 2, "user_limit": 1},
        "divine_arrival": {"global_limit": 4, "user_limit": 2},
        "play_target": {"global_limit": 10, "user_limit": 5},
    },
    window_seconds=60,
)

assert keyed_limiter.allow("timezone_wake", "u1", now_ts=0) is True
assert keyed_limiter.allow("timezone_wake", "u1", now_ts=1) is False
assert keyed_limiter.allow("divine_arrival", "u1", now_ts=2) is True
assert keyed_limiter.allow("divine_arrival", "u1", now_ts=3) is True
assert keyed_limiter.allow("divine_arrival", "u1", now_ts=4) is False
assert keyed_limiter.allow("play_target", "u1", now_ts=5) is True
assert keyed_limiter.allow("play_target", "u1", now_ts=6) is True
assert keyed_limiter.allow("play_target", "u1", now_ts=7) is True

# 测试分规则全局限流：同一规则按全局计数，不同规则互不串扰
keyed_limiter_2 = KeyedRateLimiter(
    rule_limits={
        "timezone_sleep": {"global_limit": 2, "user_limit": 2},
        "play_target": {"global_limit": 3, "user_limit": 3},
    },
    window_seconds=60,
)
assert keyed_limiter_2.allow("timezone_sleep", "u1", now_ts=0) is True
assert keyed_limiter_2.allow("timezone_sleep", "u2", now_ts=1) is True
assert keyed_limiter_2.allow("timezone_sleep", "u3", now_ts=2) is False
assert keyed_limiter_2.allow("play_target", "u4", now_ts=3) is True
assert keyed_limiter_2.allow("play_target", "u5", now_ts=4) is True
assert keyed_limiter_2.allow("play_target", "u6", now_ts=5) is True
assert keyed_limiter_2.allow("play_target", "u7", now_ts=6) is False

# 测试复读：不同人连续两条相同消息 -> 跟读
repeat_detector = GroupRepeatDetector()
assert repeat_detector.process(group_id=1001, user_id=1, text="复读") is None
repeat_reply_1 = repeat_detector.process(group_id=1001, user_id=2, text="复读")
assert repeat_reply_1 is not None
assert repeat_reply_1["rule_name"] == "repeat_follow_read"
assert repeat_reply_1["rate_limit_key"] == "repeat_follow_read"
assert repeat_reply_1["reply"] == "复读"

# 测试复读：同一人连续两条相同消息 -> 删掉最后一个字
repeat_detector_same = GroupRepeatDetector()
assert repeat_detector_same.process(group_id=1001, user_id=1, text="晚安") is None
repeat_reply_2 = repeat_detector_same.process(group_id=1001, user_id=1, text="晚安")
assert repeat_reply_2 is not None
assert repeat_reply_2["rule_name"] == "repeat_trim_last"
assert repeat_reply_2["rate_limit_key"] == "repeat_trim_last"
assert repeat_reply_2["reply"] == "晚"

# 测试复读：超过三条且全是同一人 -> 第四条警告
repeat_detector_warning = GroupRepeatDetector()
assert repeat_detector_warning.process(group_id=1001, user_id=1, text="哈哈") is None
repeat_trim = repeat_detector_warning.process(group_id=1001, user_id=1, text="哈哈")
assert repeat_trim is not None
assert repeat_trim["rule_name"] == "repeat_trim_last"
assert repeat_trim["reply"] == "哈"
assert repeat_detector_warning.process(group_id=1001, user_id=1, text="哈哈") is None
repeat_warning = repeat_detector_warning.process(group_id=1001, user_id=1, text="哈哈")
assert repeat_warning is not None
assert repeat_warning["rule_name"] == "repeat_same_user_warning"
assert repeat_warning["rate_limit_key"] == "repeat_same_user_warning"
assert repeat_warning["at_user_id"] == "1"
assert repeat_warning["reply"] == "艾斯比"

# 测试复读重叠判定：同一人四连不会在第四条再次触发删尾，而是触发警告
repeat_detector_overlap = GroupRepeatDetector()
assert repeat_detector_overlap.process(group_id=1001, user_id=9, text="测试测试") is None
assert repeat_detector_overlap.process(group_id=1001, user_id=9, text="测试测试")["rule_name"] == "repeat_trim_last"
assert repeat_detector_overlap.process(group_id=1001, user_id=9, text="测试测试") is None
assert repeat_detector_overlap.process(group_id=1001, user_id=9, text="测试测试")["rule_name"] == "repeat_same_user_warning"

# 测试复读按群隔离
repeat_detector_group = GroupRepeatDetector()
assert repeat_detector_group.process(group_id=2001, user_id=1, text="群消息") is None
assert repeat_detector_group.process(group_id=2002, user_id=2, text="群消息") is None
assert repeat_detector_group.process(group_id=2001, user_id=3, text="群消息")["rule_name"] == "repeat_follow_read"

# 测试复读状态有上限，最旧群状态会被淘汰
repeat_detector_bounded = GroupRepeatDetector(max_groups=2)
assert repeat_detector_bounded.process(group_id=1, user_id=1, text="A") is None
assert repeat_detector_bounded.process(group_id=2, user_id=1, text="B") is None
assert repeat_detector_bounded.process(group_id=3, user_id=1, text="C") is None
assert list(repeat_detector_bounded.states.keys()) == ["2", "3"]

# 测试好姐姐接龙：完整流程（交替接龙：用户说奇数位，bot 回偶数位）
chain = GoodGirlChainManager(timeout_seconds=60)
chain_start = chain.process(group_id=3001, text="阿桃是好女人吗", now_ts=0)
assert chain_start is not None
assert chain_start["rule_name"] == "good_girl_chain_start"
assert chain_start["reply"] == "别"
assert chain_start["context"]["lead_char"] == "阿"

chain_step_1 = chain.process(group_id=3001, text="逗", now_ts=1)
assert chain_step_1 is not None
assert chain_step_1["reply"] == "你"
assert chain_step_1["context"]["lead_char"] == "阿"

chain_step_2 = chain.process(group_id=3001, text="阿", now_ts=2)
assert chain_step_2 is not None
assert chain_step_2["reply"] == "姐"

chain_step_3 = chain.process(group_id=3001, text="笑", now_ts=3)
assert chain_step_3 is not None
assert chain_step_3["reply"] == "了"

# 用户说"句号"（多字元素 OR 测试），bot 以 🤣 结束链条
chain_step_4 = chain.process(group_id=3001, text="句号", now_ts=4)
assert chain_step_4 is not None
assert chain_step_4["reply"] == "🤣"
# 奇数长度：bot 说完 🤣 后会话自动终止
assert chain.process(group_id=3001, text="逗", now_ts=5) is None

# 测试好姐姐接龙：中途乱入不会打断，只会被忽略
chain_interrupt = GoodGirlChainManager(timeout_seconds=60)
assert chain_interrupt.process(group_id=3001, text="阿桃是好女人吗", now_ts=10)["reply"] == "别"
assert chain_interrupt.process(group_id=3001, text="这是一条无关消息", now_ts=11) is None
assert chain_interrupt.process(group_id=3001, text="逗", now_ts=12)["reply"] == "你"
assert chain_interrupt.process(group_id=3001, text="又一条无关消息", now_ts=13) is None
assert chain_interrupt.process(group_id=3001, text="阿", now_ts=14)["reply"] == "姐"
assert chain_interrupt.process(group_id=3001, text="笑", now_ts=15)["reply"] == "了"
# 全角句号也触发（OR 的另一侧）
assert chain_interrupt.process(group_id=3001, text="。", now_ts=16)["reply"] == "🤣"

# 测试好姐姐接龙：完成后会话结束；后续消息不会再续接
assert chain_interrupt.process(group_id=3001, text="🤣", now_ts=17) is None
assert chain_interrupt.process(group_id=3001, text="逗", now_ts=18) is None

# 测试好姐姐接龙：走完全程后会话结束，后续不会错误续接
chain_finish = GoodGirlChainManager(timeout_seconds=60)
assert chain_finish.process(group_id=3006, text="阿桃是好女人吗", now_ts=0)["reply"] == "别"
assert chain_finish.process(group_id=3006, text="逗", now_ts=1)["reply"] == "你"
assert chain_finish.process(group_id=3006, text="阿", now_ts=2)["reply"] == "姐"
assert chain_finish.process(group_id=3006, text="笑", now_ts=3)["reply"] == "了"
assert chain_finish.process(group_id=3006, text="。", now_ts=4)["reply"] == "🤣"
assert chain_finish.process(group_id=3006, text="逗", now_ts=5) is None

# 测试好姐姐接龙：中途发出 🤣 不再是终止信号，会被忽略，会话继续
chain_break = GoodGirlChainManager(timeout_seconds=60)
assert chain_break.process(group_id=3005, text="林是好姐姐吗", now_ts=0)["reply"] == "别"
assert chain_break.process(group_id=3005, text="逗", now_ts=1)["reply"] == "你"
assert chain_break.process(group_id=3005, text="🤣", now_ts=2) is None  # 不匹配，忽略
assert chain_break.process(group_id=3005, text="林", now_ts=3)["reply"] == "姐"  # 会话仍存活

# 测试好姐姐接龙：超时失效
chain_timeout = GoodGirlChainManager(timeout_seconds=5)
assert chain_timeout.process(group_id=3002, text="林是好姐姐吗", now_ts=0)["reply"] == "别"
assert chain_timeout.process(group_id=3002, text="这条乱入不应打断", now_ts=2) is None
assert chain_timeout.process(group_id=3002, text="逗", now_ts=3)["reply"] == "你"
assert chain_timeout.process(group_id=3002, text="林", now_ts=9) is None

# 测试好姐姐接龙：按群隔离
chain_group = GoodGirlChainManager(timeout_seconds=60)
assert chain_group.process(group_id=4001, text="赵云是好人吗", now_ts=0)["reply"] == "别"
assert chain_group.process(group_id=4002, text="孙尚香是好人吗", now_ts=0)["reply"] == "别"
assert chain_group.process(group_id=4001, text="逗", now_ts=1)["reply"] == "你"
assert chain_group.process(group_id=4002, text="逗", now_ts=1)["reply"] == "你"
assert chain_group.process(group_id=4001, text="赵", now_ts=2)["reply"] == "姐"
assert chain_group.process(group_id=4002, text="孙", now_ts=2)["reply"] == "姐"

# 测试好姐姐接龙：前导字与链中已有 token 重合时，仍应按顺序推进
chain_overlap_token = GoodGirlChainManager(timeout_seconds=60)
assert chain_overlap_token.process(group_id=4003, text="别人是好人吗", now_ts=0)["reply"] == "别"
assert chain_overlap_token.process(group_id=4003, text="逗", now_ts=1)["reply"] == "你"
assert chain_overlap_token.process(group_id=4003, text="别", now_ts=2)["reply"] == "姐"
assert chain_overlap_token.process(group_id=4003, text="笑", now_ts=3)["reply"] == "了"
assert chain_overlap_token.process(group_id=4003, text="句号", now_ts=4)["reply"] == "🤣"

# 测试接龙会话有上限，最旧群会话会被淘汰
chain_bounded = GoodGirlChainManager(timeout_seconds=60, max_sessions=2)
assert chain_bounded.process(group_id=5001, text="赵云是好人吗", now_ts=0)["reply"] == "别"
assert chain_bounded.process(group_id=5002, text="孙尚香是好人吗", now_ts=0)["reply"] == "别"
assert chain_bounded.process(group_id=5003, text="阿桃是好女人吗", now_ts=0)["reply"] == "别"
assert list(chain_bounded.sessions.keys()) == ["5002", "5003"]

# 测试环形差值
assert circular_diff_minutes(0, 0) == 0
assert circular_diff_minutes(100, 200) == 100
assert circular_diff_minutes(10, 1430) == 20  # 跨午夜

# ────────────────────────────────────────────────
# 测试随机回复选择
# ────────────────────────────────────────────────

# 单模板规则：select_reply_template 返回 reply_template
single_rule = {"reply_template": "固定回复"}
assert select_reply_template(single_rule) == "固定回复"

# 多模板规则：select_reply_template 返回列表中的某一个
multi_rule = {
    "reply_templates": [
        {"template": "回复A", "weight": 1},
        {"template": "回复B", "weight": 1},
        {"template": "回复C", "weight": 1},
    ]
}
random.seed(42)
results = {select_reply_template(multi_rule) for _ in range(50)}
assert results == {"回复A", "回复B", "回复C"}

# 权重倾斜测试：weight=100 的模板应占绝大多数
weighted_rule = {
    "reply_templates": [
        {"template": "常见", "weight": 100},
        {"template": "罕见", "weight": 1},
    ]
}
random.seed(0)
weighted_results = [select_reply_template(weighted_rule) for _ in range(200)]
assert weighted_results.count("常见") > 180

# reply_templates 优先于 reply_template
both_rule = {
    "reply_template": "不该被选",
    "reply_templates": [{"template": "应该被选", "weight": 1}],
}
assert select_reply_template(both_rule) == "应该被选"

# ────────────────────────────────────────────────
# 测试消息统计
# ────────────────────────────────────────────────

tracker = GroupStatsTracker()

# 记录消息（带昵称）
tracker.record_message(9001, "u1", "张三")
tracker.record_message(9001, "u2", "李四")
tracker.record_message(9001, "u1", "张三")
gs = tracker.get_stats(9001)
assert gs is not None
assert gs.total_messages == 3
assert gs.user_messages["u1"] == 2
assert gs.user_messages["u2"] == 1
assert gs.user_names["u1"] == "张三"
assert gs.user_names["u2"] == "李四"

# 记录规则触发
tracker.record_trigger(9001, "divine_arrival")
tracker.record_trigger(9001, "divine_arrival")
tracker.record_trigger(9001, "play_target")
assert gs.rule_triggers["divine_arrival"] == 2
assert gs.rule_triggers["play_target"] == 1

# 格式化输出：默认使用存储的昵称
formatted = tracker.format_stats(9001)
assert "消息总数：3" in formatted
assert "张三 — 2 条" in formatted
assert "divine_arrival — 2 次" in formatted

# 外部 name_resolver 覆盖存储的昵称
formatted_override = tracker.format_stats(9001, name_resolver={"u1": "覆盖名", "u2": "李四"})
assert "覆盖名 — 2 条" in formatted_override

# 空统计
assert tracker.format_stats(9999) == "暂无统计数据"

# 重置
tracker.reset(9001)
assert tracker.get_stats(9001) is None
assert tracker.format_stats(9001) == "暂无统计数据"

# 群隔离
tracker.record_message(8001, "u1")
tracker.record_message(8002, "u1")
assert tracker.get_stats(8001).total_messages == 1
assert tracker.get_stats(8002).total_messages == 1

# LRU 淘汰
tracker_bounded = GroupStatsTracker(max_groups=2)
tracker_bounded.record_message(1, "u1")
tracker_bounded.record_message(2, "u1")
tracker_bounded.record_message(3, "u1")
assert list(tracker_bounded.stats.keys()) == ["2", "3"]

# ────────────────────────────────────────────────
# 测试群级规则开关
# ────────────────────────────────────────────────

switch = GroupRuleSwitch()

# 默认全部启用
assert switch.is_enabled(7001, "divine_arrival") is True

# 禁用规则
assert switch.disable(7001, "divine_arrival") is True
assert switch.is_enabled(7001, "divine_arrival") is False

# 启用规则
assert switch.enable(7001, "divine_arrival") is True
assert switch.is_enabled(7001, "divine_arrival") is True

# 未知规则名 disable 返回 False
assert switch.disable(7001, "not_a_rule") is False

# 群隔离
switch.disable(7001, "play_target")
assert switch.is_enabled(7001, "play_target") is False
assert switch.is_enabled(7002, "play_target") is True

# list_disabled
switch.disable(7001, "like_reply")
disabled = switch.list_disabled(7001)
assert "play_target" in disabled
assert "like_reply" in disabled

# format_rules 包含 ON/OFF 状态
formatted_rules = switch.format_rules(7001)
assert "[OFF] play_target" in formatted_rules
assert "[ON] divine_arrival" in formatted_rules

# LRU 淘汰
switch_bounded = GroupRuleSwitch(max_groups=2)
switch_bounded.disable(1, "divine_arrival")
switch_bounded.disable(2, "divine_arrival")
switch_bounded.disable(3, "divine_arrival")
assert list(switch_bounded.disabled.keys()) == ["2", "3"]

# ────────────────────────────────────────────────
# 测试规则开关与 resolve_reply 集成
# ────────────────────────────────────────────────

# 保存并重置全局 rule_switch 状态
_saved_disabled = dict(global_rule_switch.disabled)
global_rule_switch.disabled.clear()

# 禁用 divine_arrival 后，"神临" 不再触发该规则
global_rule_switch.disable(6001, "divine_arrival")
blocked_result = resolve_reply("神临", user_id=123, sender_name="测试", group_id=6001, now=fixed_now)
assert blocked_result is None or blocked_result.get("rule_name") != "divine_arrival"

# 启用后恢复（用不同 group_id 避免复读检测干扰）
global_rule_switch.enable(6002, "divine_arrival")
restored_result = resolve_reply("神临", user_id=123, sender_name="测试", group_id=6002, now=fixed_now)
assert restored_result is not None
assert restored_result["rule_name"] == "divine_arrival"

# 不传 group_id 时规则开关不生效（向后兼容）
global_rule_switch.disable(6003, "divine_arrival")
no_group_result = resolve_reply("神临", user_id=123, sender_name="测试", now=fixed_now)
assert no_group_result is not None
assert no_group_result["rule_name"] == "divine_arrival"

# 恢复全局 rule_switch
global_rule_switch.disabled.clear()
global_rule_switch.disabled.update(_saved_disabled)

# ────────────────────────────────────────────────
# 测试持久化序列化往返
# ────────────────────────────────────────────────

# GroupStatsTracker 序列化往返
persist_tracker = GroupStatsTracker()
persist_tracker.record_message(7001, "u1", "张三")
persist_tracker.record_message(7001, "u2", "李四")
persist_tracker.record_message(7001, "u1", "张三")
persist_tracker.record_trigger(7001, "divine_arrival")
persist_tracker.record_trigger(7001, "divine_arrival")
persist_tracker.record_trigger(7001, "play_target")

snapshot = persist_tracker.to_dict()
restored_tracker = GroupStatsTracker()
restored_tracker.from_dict(snapshot)
rgs = restored_tracker.get_stats(7001)
assert rgs is not None
assert rgs.total_messages == 3
assert rgs.user_messages["u1"] == 2
assert rgs.user_names["u1"] == "张三"
assert rgs.rule_triggers["divine_arrival"] == 2

artifact_dir = Path("dev/sandbox/test_artifacts/test_tz")
if artifact_dir.exists():
    shutil.rmtree(artifact_dir)
artifact_dir.mkdir(parents=True, exist_ok=True)

# 文件 save/load 往返
stats_file = artifact_dir / "stats.json"
persist_tracker.save(stats_file)
loaded_tracker = GroupStatsTracker()
loaded_tracker.load(stats_file)
lgs = loaded_tracker.get_stats(7001)
assert lgs is not None
assert lgs.total_messages == 3
assert lgs.user_names["u1"] == "张三"

# load 不存在的文件不报错
empty_tracker = GroupStatsTracker()
empty_tracker.load("/nonexistent/path/stats.json")
assert len(empty_tracker.stats) == 0

# GroupRuleSwitch 序列化往返
persist_switch = GroupRuleSwitch()
persist_switch.disable(7001, "divine_arrival")
persist_switch.disable(7001, "play_target")
persist_switch.disable(7002, "like_reply")

snapshot_sw = persist_switch.to_dict()
restored_switch = GroupRuleSwitch()
restored_switch.from_dict(snapshot_sw)
assert restored_switch.is_enabled(7001, "divine_arrival") is False
assert restored_switch.is_enabled(7001, "play_target") is False
assert restored_switch.is_enabled(7002, "like_reply") is False
assert restored_switch.is_enabled(7001, "like_reply") is True

# 文件 save/load 往返
switch_file = artifact_dir / "rule_switch.json"
persist_switch.save(switch_file)
loaded_switch = GroupRuleSwitch()
loaded_switch.load(switch_file)
assert loaded_switch.is_enabled(7001, "divine_arrival") is False
assert loaded_switch.is_enabled(7002, "like_reply") is False

# load 不存在的文件不报错
empty_switch = GroupRuleSwitch()
empty_switch.load("/nonexistent/path/switch.json")
assert len(empty_switch.disabled) == 0

# ══════════════════════════════════════════════════════════
# ChainGameManager 专项测试
# ══════════════════════════════════════════════════════════

import re as _re  # noqa: E402

# ── 辅助：快速构造 ChainGameDef ──────────────────────────────
def _def(name, pattern, chain, timeout=60, rate_limit_key="test_chain"):
    return ChainGameDef(
        name=name,
        trigger_pattern=_re.compile(pattern),
        chain_template=chain,
        timeout_seconds=timeout,
        rate_limit_key=rate_limit_key,
    )


# ── 测试：$1 完整捕获组 ──────────────────────────────────────
cg_full = ChainGameManager([_def("full_group", r"^来一个(.+)$", ["好的", "$1", "666"])])
r = cg_full.process(group_id=1, text="来一个哈哈哈", now_ts=0)
assert r is not None and r["reply"] == "好的"
assert r["rule_name"] == "full_group_start"
# 用户发完整捕获组文本 "哈哈哈"
r = cg_full.process(group_id=1, text="哈哈哈", now_ts=1)
assert r is not None and r["reply"] == "666"
assert r["rule_name"] == "full_group_progress"
# 奇数长度：bot 最后一个回复发出后会话结束
assert cg_full.process(group_id=1, text="哈哈哈", now_ts=2) is None

# ── 测试：$1[0] 首字 ─────────────────────────────────────────
cg_first = ChainGameManager([_def("first_char", r"^(.+?)说$", ["嗯", "$1[0]", "好"])])
r = cg_first.process(group_id=2, text="阿弥陀佛说", now_ts=0)
assert r is not None and r["reply"] == "嗯"
r = cg_first.process(group_id=2, text="阿", now_ts=1)  # 只接受首字
assert r is not None and r["reply"] == "好"
# 会话结束，再次发送无效
assert cg_first.process(group_id=2, text="阿", now_ts=2) is None

# ── 测试：$1[-1] 尾字 ────────────────────────────────────────
cg_last = ChainGameManager([_def("last_char", r"^(.+?)好$", ["来", "$1[-1]", "哦"])])
r = cg_last.process(group_id=3, text="挺好", now_ts=0)
assert r is not None and r["reply"] == "来"
r = cg_last.process(group_id=3, text="挺", now_ts=1)  # 尾字是"挺"
assert r is not None and r["reply"] == "哦"

# ── 测试：$1[1] 第二字 ───────────────────────────────────────
cg_second = ChainGameManager([_def("second_char", r"^(.+)开始$", ["走", "$1[1]", "完"])])
r = cg_second.process(group_id=4, text="AB开始", now_ts=0)
assert r is not None and r["reply"] == "走"
r = cg_second.process(group_id=4, text="B", now_ts=1)  # 第二字 index=1
assert r is not None and r["reply"] == "完"

# ── 测试：多字元素 ──────────────────────────────────────────
cg_multi = ChainGameManager([_def("multi_tok", r"^(.+)发车$", ["上车了", "准备好了", "出发！"])])
r = cg_multi.process(group_id=5, text="快速发车", now_ts=0)
assert r is not None and r["reply"] == "上车了"
r = cg_multi.process(group_id=5, text="准备好了", now_ts=1)
assert r is not None and r["reply"] == "出发！"
# 奇数长度，会话结束
assert cg_multi.process(group_id=5, text="准备好了", now_ts=2) is None

# ── 测试：偶数长度 + 静默终止 token ─────────────────────────
cg_even = ChainGameManager([_def("even_chain", r"^(.+)启动$", ["准备", "就绪", "冲", "STOP"])])
r = cg_even.process(group_id=6, text="快速启动", now_ts=0)
assert r is not None and r["reply"] == "准备"
r = cg_even.process(group_id=6, text="就绪", now_ts=1)
assert r is not None and r["reply"] == "冲"
# 终止 token 结束会话（无回复）
r = cg_even.process(group_id=6, text="STOP", now_ts=2)
assert r is None
# 会话已结束，无法续接
assert cg_even.process(group_id=6, text="就绪", now_ts=3) is None

# ── 测试：偶数长度，终止 token 可提前触发 ───────────────────
cg_early_stop = ChainGameManager([_def("early_stop", r"^(.+)启动$", ["准备", "就绪", "冲", "STOP"])])
cg_early_stop.process(group_id=7, text="快速启动", now_ts=0)
# 未完成接龙直接发 STOP
assert cg_early_stop.process(group_id=7, text="STOP", now_ts=1) is None
# 会话已结束
assert cg_early_stop.process(group_id=7, text="就绪", now_ts=2) is None

# ── 测试：错误输入被忽略，接龙不中断 ────────────────────────
cg_noise = ChainGameManager([_def("noise_test", r"^(.+)准备$", ["好", "开始", "完成"])])
cg_noise.process(group_id=8, text="ABC准备", now_ts=0)
assert cg_noise.process(group_id=8, text="无关消息", now_ts=1) is None
r = cg_noise.process(group_id=8, text="开始", now_ts=2)
assert r is not None and r["reply"] == "完成"

# ── 测试：超时后会话失效 ─────────────────────────────────────
cg_timeout2 = ChainGameManager([_def("timeout_test", r"^(.+)准备$", ["好", "开始", "完成"], timeout=5)])
cg_timeout2.process(group_id=9, text="ABC准备", now_ts=0)
assert cg_timeout2.process(group_id=9, text="开始", now_ts=6) is None  # 超时

# ── 测试：多群隔离 ───────────────────────────────────────────
cg_groups2 = ChainGameManager([_def("groups_test", r"^(.+)来$", ["哦", "$1[0]", "好"])])
cg_groups2.process(group_id=10, text="阿来", now_ts=0)
cg_groups2.process(group_id=11, text="哟来", now_ts=0)
assert cg_groups2.process(group_id=10, text="阿", now_ts=1)["reply"] == "好"
assert cg_groups2.process(group_id=11, text="哟", now_ts=1)["reply"] == "好"

# ── 测试：ChainGameDef.from_dict ────────────────────────────
d = ChainGameDef.from_dict({
    "name": "dict_chain",
    "trigger_pattern": r"^test(.+)$",
    "chain": ["A", "$1", "B"],
    "timeout_seconds": 30,
    "rate_limit_key": "test_bucket",
})
cg_dict = ChainGameManager([d])
r = cg_dict.process(group_id=20, text="testXY", now_ts=0)
assert r is not None and r["reply"] == "A"
assert cg_dict.process(group_id=20, text="XY", now_ts=1)["reply"] == "B"

# ── 测试：OR 匹配（pipe 分隔的多个候选 token）──────────────
cg_or = ChainGameManager([_def("or_test", r"^(.+)出发$", ["准备", "就绪|ready|OK", "出发！"])])
# 每个 group 独立测一种候选
assert cg_or.process(group_id=40, text="快速出发", now_ts=0)["reply"] == "准备"
assert cg_or.process(group_id=40, text="就绪", now_ts=1)["reply"] == "出发！"   # 候选1

assert cg_or.process(group_id=41, text="快速出发", now_ts=0)["reply"] == "准备"
assert cg_or.process(group_id=41, text="ready", now_ts=1)["reply"] == "出发！"  # 候选2

assert cg_or.process(group_id=42, text="快速出发", now_ts=0)["reply"] == "准备"
assert cg_or.process(group_id=42, text="OK", now_ts=1)["reply"] == "出发！"     # 候选3

# 不在候选列表中的输入被忽略，会话仍存活
assert cg_or.process(group_id=43, text="快速出发", now_ts=0)["reply"] == "准备"
assert cg_or.process(group_id=43, text="差不多得了", now_ts=1) is None          # 不匹配
assert cg_or.process(group_id=43, text="OK", now_ts=2)["reply"] == "出发！"     # 会话仍存活

# ── 测试：context["groups"] 正确暴露 ────────────────────────
cg_ctx = ChainGameManager([_def("ctx_test", r"^(.+?)和(.+?)$", ["好的", "$1", "完"])])
r = cg_ctx.process(group_id=30, text="猫和狗", now_ts=0)
assert r["context"]["groups"] == ("猫", "狗")
r2 = cg_ctx.process(group_id=30, text="猫", now_ts=1)
assert r2["context"]["groups"] == ("猫", "狗")

print("所有测试通过")
