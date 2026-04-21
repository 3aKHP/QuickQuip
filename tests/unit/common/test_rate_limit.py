from __future__ import annotations

from quickquip.common.rate_limit import KeyedRateLimiter, SlidingWindowRateLimiter


def test_sliding_window_basic():
    limiter = SlidingWindowRateLimiter(global_limit=4, user_limit=2, window_seconds=60)
    assert limiter.allow("u1", now_ts=0) is True
    assert limiter.allow("u1", now_ts=10) is True
    # user_limit=2 exhausted
    assert limiter.allow("u1", now_ts=20) is False
    # window slides past the first hit
    assert limiter.allow("u1", now_ts=61) is True


def test_keyed_rate_limiter_keys_are_independent():
    limiter = KeyedRateLimiter(
        rule_limits={
            "timezone_wake": {"global_limit": 2, "user_limit": 1},
            "divine_arrival": {"global_limit": 4, "user_limit": 2},
            "play_target": {"global_limit": 10, "user_limit": 5},
        },
        window_seconds=60,
    )
    assert limiter.allow("timezone_wake", "u1", now_ts=0) is True
    assert limiter.allow("timezone_wake", "u1", now_ts=1) is False
    assert limiter.allow("divine_arrival", "u1", now_ts=2) is True
    assert limiter.allow("divine_arrival", "u1", now_ts=3) is True
    assert limiter.allow("divine_arrival", "u1", now_ts=4) is False
    assert limiter.allow("play_target", "u1", now_ts=5) is True
    assert limiter.allow("play_target", "u1", now_ts=6) is True
    assert limiter.allow("play_target", "u1", now_ts=7) is True


def test_keyed_rate_limiter_global_per_rule():
    limiter = KeyedRateLimiter(
        rule_limits={
            "timezone_sleep": {"global_limit": 2, "user_limit": 2},
            "play_target": {"global_limit": 3, "user_limit": 3},
        },
        window_seconds=60,
    )
    assert limiter.allow("timezone_sleep", "u1", now_ts=0) is True
    assert limiter.allow("timezone_sleep", "u2", now_ts=1) is True
    # global_limit=2 exhausted across users
    assert limiter.allow("timezone_sleep", "u3", now_ts=2) is False
    assert limiter.allow("play_target", "u4", now_ts=3) is True
    assert limiter.allow("play_target", "u5", now_ts=4) is True
    assert limiter.allow("play_target", "u6", now_ts=5) is True
    assert limiter.allow("play_target", "u7", now_ts=6) is False


def test_keyed_rate_limiter_per_rule_window():
    limiter = KeyedRateLimiter(
        rule_limits={
            "fast": {"global_limit": 1, "user_limit": 1, "window": 1},
            "slow": {"global_limit": 1, "user_limit": 1, "window": 120},
        },
        window_seconds=60,
    )
    assert limiter.allow("fast", "u1", now_ts=0) is True
    assert limiter.allow("fast", "u1", now_ts=0.5) is False
    # fast window is 1s
    assert limiter.allow("fast", "u1", now_ts=1.2) is True

    assert limiter.allow("slow", "u1", now_ts=0) is True
    # slow window is 120s; still blocked at 60s
    assert limiter.allow("slow", "u1", now_ts=60) is False
    assert limiter.allow("slow", "u1", now_ts=121) is True


def test_keyed_rate_limiter_window_fallback_to_default():
    limiter = KeyedRateLimiter(
        rule_limits={"plain": {"global_limit": 1, "user_limit": 1}},
        window_seconds=5,
    )
    snapshot = limiter.snapshot(now_ts=0)
    assert snapshot["plain"]["window_seconds"] == 5


def test_keyed_rate_limiter_reload_drops_changed_buckets():
    limiter = KeyedRateLimiter(
        rule_limits={
            "stable": {"global_limit": 2, "user_limit": 2},
            "changing": {"global_limit": 2, "user_limit": 2, "window": 60},
            "removed": {"global_limit": 1, "user_limit": 1},
        },
        window_seconds=60,
    )
    # Prime buckets.
    limiter.allow("stable", "u1", now_ts=0)
    limiter.allow("changing", "u1", now_ts=0)
    limiter.allow("removed", "u1", now_ts=0)

    limiter.reload_rules(
        {
            "stable": {"global_limit": 2, "user_limit": 2},
            "changing": {"global_limit": 2, "user_limit": 2, "window": 10},
            "brand_new": {"global_limit": 1, "user_limit": 1},
        }
    )

    # stable: identical config → bucket preserved, so second hit trips user_limit=2 still.
    assert limiter.allow("stable", "u1", now_ts=1) is True
    assert limiter.allow("stable", "u1", now_ts=2) is False
    # changing: window changed → bucket dropped, fresh budget.
    assert limiter.allow("changing", "u1", now_ts=1) is True
    assert limiter.allow("changing", "u1", now_ts=2) is True
    # removed: rule gone → limiter.allow returns True unconditionally.
    assert limiter.allow("removed", "u1", now_ts=1) is True
    # brand_new: new rule honoured.
    assert limiter.allow("brand_new", "u1", now_ts=1) is True
    assert limiter.allow("brand_new", "u1", now_ts=2) is False
