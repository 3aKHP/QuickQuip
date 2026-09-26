from __future__ import annotations

from quickquip.chat.good_girl_chain import GoodGirlChainManager


def test_full_chain_completes_and_ends():
    chain = GoodGirlChainManager(timeout_seconds=60)
    start = chain.process(group_id=3001, text="阿桃是好女人吗", now_ts=0)
    assert start is not None
    assert start["rule_name"] == "good_girl_chain_start"
    assert start["reply"] == "别"
    assert start["context"]["lead_char"] == "阿"

    assert chain.process(group_id=3001, text="逗", now_ts=1)["reply"] == "你"
    assert chain.process(group_id=3001, text="阿", now_ts=2)["reply"] == "姐"
    assert chain.process(group_id=3001, text="笑", now_ts=3)["reply"] == "了"
    assert chain.process(group_id=3001, text="句号", now_ts=4)["reply"] == "🤣"
    # 奇数长度完成后会话终止
    assert chain.process(group_id=3001, text="逗", now_ts=5) is None


def test_timeout_invalidates_session():
    chain = GoodGirlChainManager(timeout_seconds=5)
    assert chain.process(group_id=3002, text="林是好姐姐吗", now_ts=0)["reply"] == "别"
    assert chain.process(group_id=3002, text="这条乱入不应打断", now_ts=2) is None
    assert chain.process(group_id=3002, text="逗", now_ts=3)["reply"] == "你"
    assert chain.process(group_id=3002, text="林", now_ts=9) is None


def test_lead_char_overlapping_with_chain_token():
    chain = GoodGirlChainManager(timeout_seconds=60)
    assert chain.process(group_id=4003, text="别人是好人吗", now_ts=0)["reply"] == "别"
    assert chain.process(group_id=4003, text="逗", now_ts=1)["reply"] == "你"
    assert chain.process(group_id=4003, text="别", now_ts=2)["reply"] == "姐"
    assert chain.process(group_id=4003, text="笑", now_ts=3)["reply"] == "了"
    assert chain.process(group_id=4003, text="句号", now_ts=4)["reply"] == "🤣"


def test_lru_eviction():
    chain = GoodGirlChainManager(timeout_seconds=60, max_sessions=2)
    chain.process(group_id=5001, text="赵云是好人吗", now_ts=0)
    chain.process(group_id=5002, text="孙尚香是好人吗", now_ts=0)
    chain.process(group_id=5003, text="阿桃是好女人吗", now_ts=0)
    assert list(chain.sessions.keys()) == ["5002", "5003"]
