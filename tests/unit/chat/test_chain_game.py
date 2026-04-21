from __future__ import annotations

from plugins.chain_game import ChainGameDef, ChainGameManager

from tests.fixtures.chain_game import make_chain_def


class TestFullCapture:
    def test_start_and_progress(self):
        cg = ChainGameManager([make_chain_def("full_group", r"^来一个(.+)$", ["好的", "$1", "666"])])
        r = cg.process(group_id=1, text="来一个哈哈哈", now_ts=0)
        assert r is not None and r["reply"] == "好的"
        assert r["rule_name"] == "full_group_start"
        r = cg.process(group_id=1, text="哈哈哈", now_ts=1)
        assert r is not None and r["reply"] == "666"
        assert r["rule_name"] == "full_group_progress"

    def test_session_ends_after_odd_chain(self):
        cg = ChainGameManager([make_chain_def("full_group", r"^来一个(.+)$", ["好的", "$1", "666"])])
        cg.process(group_id=1, text="来一个哈哈哈", now_ts=0)
        cg.process(group_id=1, text="哈哈哈", now_ts=1)
        assert cg.process(group_id=1, text="哈哈哈", now_ts=2) is None


class TestCharIndexing:
    def test_first_char(self):
        cg = ChainGameManager([make_chain_def("first_char", r"^(.+?)说$", ["嗯", "$1[0]", "好"])])
        assert cg.process(group_id=2, text="阿弥陀佛说", now_ts=0)["reply"] == "嗯"
        assert cg.process(group_id=2, text="阿", now_ts=1)["reply"] == "好"
        assert cg.process(group_id=2, text="阿", now_ts=2) is None

    def test_last_char(self):
        cg = ChainGameManager([make_chain_def("last_char", r"^(.+?)好$", ["来", "$1[-1]", "哦"])])
        assert cg.process(group_id=3, text="挺好", now_ts=0)["reply"] == "来"
        assert cg.process(group_id=3, text="挺", now_ts=1)["reply"] == "哦"

    def test_second_char(self):
        cg = ChainGameManager([make_chain_def("second_char", r"^(.+)开始$", ["走", "$1[1]", "完"])])
        assert cg.process(group_id=4, text="AB开始", now_ts=0)["reply"] == "走"
        assert cg.process(group_id=4, text="B", now_ts=1)["reply"] == "完"


class TestChainShape:
    def test_multi_character_token(self):
        cg = ChainGameManager([make_chain_def("multi_tok", r"^(.+)发车$", ["上车了", "准备好了", "出发！"])])
        assert cg.process(group_id=5, text="快速发车", now_ts=0)["reply"] == "上车了"
        assert cg.process(group_id=5, text="准备好了", now_ts=1)["reply"] == "出发！"
        assert cg.process(group_id=5, text="准备好了", now_ts=2) is None

    def test_even_length_with_stop_token(self):
        cg = ChainGameManager([make_chain_def("even_chain", r"^(.+)启动$", ["准备", "就绪", "冲", "STOP"])])
        assert cg.process(group_id=6, text="快速启动", now_ts=0)["reply"] == "准备"
        assert cg.process(group_id=6, text="就绪", now_ts=1)["reply"] == "冲"
        assert cg.process(group_id=6, text="STOP", now_ts=2) is None
        assert cg.process(group_id=6, text="就绪", now_ts=3) is None

    def test_stop_token_ends_session_early(self):
        cg = ChainGameManager([make_chain_def("early_stop", r"^(.+)启动$", ["准备", "就绪", "冲", "STOP"])])
        cg.process(group_id=7, text="快速启动", now_ts=0)
        assert cg.process(group_id=7, text="STOP", now_ts=1) is None
        assert cg.process(group_id=7, text="就绪", now_ts=2) is None


class TestNoiseAndTimeout:
    def test_noise_does_not_break_chain(self):
        cg = ChainGameManager([make_chain_def("noise_test", r"^(.+)准备$", ["好", "开始", "完成"])])
        cg.process(group_id=8, text="ABC准备", now_ts=0)
        assert cg.process(group_id=8, text="无关消息", now_ts=1) is None
        assert cg.process(group_id=8, text="开始", now_ts=2)["reply"] == "完成"

    def test_timeout_invalidates_session(self):
        cg = ChainGameManager([make_chain_def("timeout", r"^(.+)准备$", ["好", "开始", "完成"], timeout=5)])
        cg.process(group_id=9, text="ABC准备", now_ts=0)
        assert cg.process(group_id=9, text="开始", now_ts=6) is None


def test_group_isolation():
    cg = ChainGameManager([make_chain_def("groups", r"^(.+)来$", ["哦", "$1[0]", "好"])])
    cg.process(group_id=10, text="阿来", now_ts=0)
    cg.process(group_id=11, text="哟来", now_ts=0)
    assert cg.process(group_id=10, text="阿", now_ts=1)["reply"] == "好"
    assert cg.process(group_id=11, text="哟", now_ts=1)["reply"] == "好"


def test_chaingamedef_from_dict():
    d = ChainGameDef.from_dict({
        "name": "dict_chain",
        "trigger_pattern": r"^test(.+)$",
        "chain": ["A", "$1", "B"],
        "timeout_seconds": 30,
        "rate_limit_key": "test_bucket",
    })
    cg = ChainGameManager([d])
    assert cg.process(group_id=20, text="testXY", now_ts=0)["reply"] == "A"
    assert cg.process(group_id=20, text="XY", now_ts=1)["reply"] == "B"


class TestOrCandidates:
    def test_each_alternative_matches(self):
        cg = ChainGameManager([make_chain_def("or_test", r"^(.+)出发$", ["准备", "就绪|ready|OK", "出发！"])])
        assert cg.process(group_id=40, text="快速出发", now_ts=0)["reply"] == "准备"
        assert cg.process(group_id=40, text="就绪", now_ts=1)["reply"] == "出发！"

        assert cg.process(group_id=41, text="快速出发", now_ts=0)["reply"] == "准备"
        assert cg.process(group_id=41, text="ready", now_ts=1)["reply"] == "出发！"

        assert cg.process(group_id=42, text="快速出发", now_ts=0)["reply"] == "准备"
        assert cg.process(group_id=42, text="OK", now_ts=1)["reply"] == "出发！"

    def test_non_candidate_ignored_session_survives(self):
        cg = ChainGameManager([make_chain_def("or_test", r"^(.+)出发$", ["准备", "就绪|ready|OK", "出发！"])])
        assert cg.process(group_id=43, text="快速出发", now_ts=0)["reply"] == "准备"
        assert cg.process(group_id=43, text="差不多得了", now_ts=1) is None
        assert cg.process(group_id=43, text="OK", now_ts=2)["reply"] == "出发！"


def test_context_exposes_groups_tuple():
    cg = ChainGameManager([make_chain_def("ctx_test", r"^(.+?)和(.+?)$", ["好的", "$1", "完"])])
    r = cg.process(group_id=30, text="猫和狗", now_ts=0)
    assert r["context"]["groups"] == ("猫", "狗")
    r2 = cg.process(group_id=30, text="猫", now_ts=1)
    assert r2["context"]["groups"] == ("猫", "狗")
