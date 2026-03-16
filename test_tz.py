from datetime import datetime, time
from zoneinfo import ZoneInfo

from plugins.good_girl_chain import GoodGirlChainManager
from plugins.rate_limit import KeyedRateLimiter, SlidingWindowRateLimiter
from plugins.repeat_detector import GroupRepeatDetector
from plugins.text_reply_rules import match_text_rule
from plugins.tz_tackcer import (
    build_reply,
    build_timezone_reply,
    circular_diff_minutes,
    detect_kind,
    find_best_timezones,
    format_city_zh,
    format_location_zh,
    resolve_reply,
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

rule_reply_3 = match_text_rule("你喜欢苹果", user_id=123456, sender_name="测试用户", now=fixed_now)
assert rule_reply_3 is not None
assert rule_reply_3["rule_name"] == "like_reply"
assert rule_reply_3["rate_limit_key"] == "like_reply"
assert rule_reply_3["reply"].startswith("还在")

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

# 测试好姐姐接龙：完整流程（监听任意单字并输出下一个单字）
chain = GoodGirlChainManager(timeout_seconds=60)
chain_start = chain.process(group_id=3001, text="阿桃是好女人吗", now_ts=0)
assert chain_start is not None
assert chain_start["rule_name"] == "good_girl_chain_start"
assert chain_start["reply"] == "别"
assert chain_start["context"]["lead_char"] == "阿"

chain_step_1 = chain.process(group_id=3001, text="别", now_ts=1)
assert chain_step_1 is not None
assert chain_step_1["reply"] == "逗"
assert chain_step_1["context"]["lead_char"] == "阿"

chain_step_2 = chain.process(group_id=3001, text="逗", now_ts=2)
assert chain_step_2 is not None
assert chain_step_2["reply"] == "你"

chain_step_3 = chain.process(group_id=3001, text="你", now_ts=3)
assert chain_step_3 is not None
assert chain_step_3["reply"] == "阿"

chain_step_4 = chain.process(group_id=3001, text="阿", now_ts=4)
assert chain_step_4 is not None
assert chain_step_4["reply"] == "姐"

chain_step_5 = chain.process(group_id=3001, text="姐", now_ts=5)
assert chain_step_5 is not None
assert chain_step_5["reply"] == "笑"

chain_step_6 = chain.process(group_id=3001, text="笑", now_ts=6)
assert chain_step_6 is not None
assert chain_step_6["reply"] == "了"

chain_step_7 = chain.process(group_id=3001, text="了", now_ts=7)
assert chain_step_7 is not None
assert chain_step_7["reply"] == "🤣"

# 测试好姐姐接龙：中途乱入不会打断，只会被忽略
chain_interrupt = GoodGirlChainManager(timeout_seconds=60)
assert chain_interrupt.process(group_id=3001, text="阿桃是好女人吗", now_ts=10)["reply"] == "别"
assert chain_interrupt.process(group_id=3001, text="这是一条无关消息", now_ts=11) is None
assert chain_interrupt.process(group_id=3001, text="别", now_ts=12)["reply"] == "逗"
assert chain_interrupt.process(group_id=3001, text="又一条无关消息", now_ts=13) is None
assert chain_interrupt.process(group_id=3001, text="逗", now_ts=14)["reply"] == "你"
assert chain_interrupt.process(group_id=3001, text="你", now_ts=15)["reply"] == "阿"
assert chain_interrupt.process(group_id=3001, text="阿", now_ts=16)["reply"] == "姐"
assert chain_interrupt.process(group_id=3001, text="姐", now_ts=17)["reply"] == "笑"
assert chain_interrupt.process(group_id=3001, text="笑", now_ts=18)["reply"] == "了"
assert chain_interrupt.process(group_id=3001, text="了", now_ts=19)["reply"] == "🤣"

# 测试好姐姐接龙：完成后会话结束；收到🤣后不会再继续
assert chain_interrupt.process(group_id=3001, text="🤣", now_ts=20) is None
assert chain_interrupt.process(group_id=3001, text="别", now_ts=21) is None

# 测试好姐姐接龙：机器人发出🤣后，会话应立即结束，后续不会错误续接
chain_finish = GoodGirlChainManager(timeout_seconds=60)
assert chain_finish.process(group_id=3006, text="阿桃是好女人吗", now_ts=0)["reply"] == "别"
assert chain_finish.process(group_id=3006, text="别", now_ts=1)["reply"] == "逗"
assert chain_finish.process(group_id=3006, text="逗", now_ts=2)["reply"] == "你"
assert chain_finish.process(group_id=3006, text="你", now_ts=3)["reply"] == "阿"
assert chain_finish.process(group_id=3006, text="阿", now_ts=4)["reply"] == "姐"
assert chain_finish.process(group_id=3006, text="姐", now_ts=5)["reply"] == "笑"
assert chain_finish.process(group_id=3006, text="笑", now_ts=6)["reply"] == "了"
assert chain_finish.process(group_id=3006, text="了", now_ts=7)["reply"] == "🤣"
assert chain_finish.process(group_id=3006, text="别", now_ts=8) is None

# 测试好姐姐接龙：收到🤣会主动终止链条
chain_break = GoodGirlChainManager(timeout_seconds=60)
assert chain_break.process(group_id=3005, text="林是好姐姐吗", now_ts=0)["reply"] == "别"
assert chain_break.process(group_id=3005, text="别", now_ts=1)["reply"] == "逗"
assert chain_break.process(group_id=3005, text="🤣", now_ts=2) is None
assert chain_break.process(group_id=3005, text="逗", now_ts=3) is None

# 测试好姐姐接龙：超时失效
chain_timeout = GoodGirlChainManager(timeout_seconds=5)
assert chain_timeout.process(group_id=3002, text="林是好姐姐吗", now_ts=0)["reply"] == "别"
assert chain_timeout.process(group_id=3002, text="这条乱入不应打断", now_ts=2) is None
assert chain_timeout.process(group_id=3002, text="别", now_ts=3)["reply"] == "逗"
assert chain_timeout.process(group_id=3002, text="逗", now_ts=9) is None

# 测试好姐姐接龙：按群隔离
chain_group = GoodGirlChainManager(timeout_seconds=60)
assert chain_group.process(group_id=4001, text="赵云是好人吗", now_ts=0)["reply"] == "别"
assert chain_group.process(group_id=4002, text="孙尚香是好人吗", now_ts=0)["reply"] == "别"
assert chain_group.process(group_id=4001, text="别", now_ts=1)["reply"] == "逗"
assert chain_group.process(group_id=4002, text="别", now_ts=1)["reply"] == "逗"
assert chain_group.process(group_id=4001, text="逗", now_ts=2)["reply"] == "你"
assert chain_group.process(group_id=4002, text="逗", now_ts=2)["reply"] == "你"
assert chain_group.process(group_id=4001, text="你", now_ts=3)["reply"] == "赵"
assert chain_group.process(group_id=4002, text="你", now_ts=3)["reply"] == "孙"

# 测试好姐姐接龙：前导字与链中已有 token 重合时，仍应按顺序推进
chain_overlap_token = GoodGirlChainManager(timeout_seconds=60)
assert chain_overlap_token.process(group_id=4003, text="别人是好人吗", now_ts=0)["reply"] == "别"
assert chain_overlap_token.process(group_id=4003, text="别", now_ts=1)["reply"] == "逗"
assert chain_overlap_token.process(group_id=4003, text="逗", now_ts=2)["reply"] == "你"
assert chain_overlap_token.process(group_id=4003, text="你", now_ts=3)["reply"] == "别"
assert chain_overlap_token.process(group_id=4003, text="别", now_ts=4)["reply"] == "姐"
assert chain_overlap_token.process(group_id=4003, text="姐", now_ts=5)["reply"] == "笑"
assert chain_overlap_token.process(group_id=4003, text="笑", now_ts=6)["reply"] == "了"
assert chain_overlap_token.process(group_id=4003, text="了", now_ts=7)["reply"] == "🤣"

# 测试环形差值
assert circular_diff_minutes(0, 0) == 0
assert circular_diff_minutes(100, 200) == 100
assert circular_diff_minutes(10, 1430) == 20  # 跨午夜

print("所有测试通过")
