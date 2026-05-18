"""Tests for 牛牛大作战 module (niuniu)."""

from __future__ import annotations

import random
import time
from pathlib import Path

import pytest

from quickquip.games.config import NiuNiuConfig
from quickquip.games.niuniu import (
    CooldownTracker,
    NiuNiuStore,
    _apply_decay,
    arrested_cd,
    fence_cd,
    fenced_cd,
    fencing,
    get_comment,
    glue_cd,
    gluing,
)
from quickquip.games.niuniu.events import (
    FENCE_EVENTS,
    GLUE_EVENTS,
    NO_NIUNIU_EVENTS,
    _normal_fence_event,
)
from quickquip.games.niuniu.fencing import _fence_win_prob, _fence_winner_is_role
from quickquip.games.niuniu.gluing import _glue_growth
from quickquip.games.niuniu.store import _roll_lognormal


# ── helpers ────────────────────────────────────────────────────────────────


def _clear_cd_trackers() -> None:
    for t in [glue_cd, fence_cd, fenced_cd, arrested_cd]:
        t._cd.clear()


def _patch_glue_event(monkeypatch, event_name: str):
    """Force gluing's random.choices to return *event_name* (a string)."""
    monkeypatch.setattr(
        random, "choices", lambda population, weights=None, k=1: [event_name]
    )


def _patch_fence_event(monkeypatch, event_name: str):
    """Force fencing's random.choices to return the named event dict."""
    event = next(e for e in FENCE_EVENTS if e["name"] == event_name)
    monkeypatch.setattr(
        random, "choices", lambda population, weights=None, k=1: [event]
    )


def _patch_no_niuniu_event(monkeypatch, event_name: str):
    """Force _fence_no_target's random.choices to return the named event dict."""
    event = next(e for e in NO_NIUNIU_EVENTS if e["name"] == event_name)
    monkeypatch.setattr(
        random, "choices", lambda population, weights=None, k=1: [event]
    )


def _patch_uniform(monkeypatch, value: float):
    monkeypatch.setattr(random, "uniform", lambda a, b: value)


def _patch_random(monkeypatch, value: float):
    monkeypatch.setattr(random, "random", lambda: value)


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_cds():
    _clear_cd_trackers()
    yield
    _clear_cd_trackers()


@pytest.fixture
def store(tmp_path: Path) -> NiuNiuStore:
    return NiuNiuStore(str(tmp_path / "test_niuniu.db"))


@pytest.fixture
def uid_a(store: NiuNiuStore) -> str:
    store.register("111")
    return "111"


@pytest.fixture
def uid_b(store: NiuNiuStore) -> str:
    store.register("222")
    return "222"


# ═══════════════════════════════════════════════════════════════════════════
# CooldownTracker
# ═══════════════════════════════════════════════════════════════════════════


class TestCooldownTracker:
    def test_fresh_returns_zero(self):
        ct = CooldownTracker()
        assert ct.check("x") == 0.0

    def test_set_then_check_returns_remaining(self):
        ct = CooldownTracker()
        ct.set("x", 60)
        r = ct.check("x")
        assert 59 <= r <= 60

    def test_expired_returns_zero_and_cleans_up(self, monkeypatch):
        ct = CooldownTracker()
        ct.set("x", 60)
        monkeypatch.setattr(time, "time", lambda: ct._cd.get("x", 0) + 1)
        assert ct.check("x") == 0.0
        assert "x" not in ct._cd

    def test_clear_removes_entry(self):
        ct = CooldownTracker()
        ct.set("x", 999)
        ct.clear("x")
        assert ct.check("x") == 0.0

    def test_multiple_users_independent(self):
        ct = CooldownTracker()
        ct.set("a", 60)
        ct.set("b", 120)
        assert ct.check("a") > 0
        assert ct.check("b") > 0
        ct.clear("a")
        assert ct.check("a") == 0.0
        assert ct.check("b") > 0  # b untouched


# ═══════════════════════════════════════════════════════════════════════════
# _roll_lognormal
# ═══════════════════════════════════════════════════════════════════════════


class TestRollLognormal:
    def test_never_negative(self):
        for _ in range(500):
            assert _roll_lognormal(1.0) >= 0

    def test_median_near_one(self):
        samples = sorted(_roll_lognormal(1.0) for _ in range(2000))
        median = samples[len(samples) // 2]
        assert 0.7 <= median <= 1.4

    def test_about_half_below_one(self):
        below = sum(1 for _ in range(2000) if _roll_lognormal(1.0) < 1.0)
        assert 900 <= below <= 1100

    def test_sigma_zero_always_returns_one(self, monkeypatch):
        monkeypatch.setattr(random, "gauss", lambda mu, sigma: 0.0)
        assert _roll_lognormal(0.5) == 1.0


# ═══════════════════════════════════════════════════════════════════════════
# get_comment
# ═══════════════════════════════════════════════════════════════════════════


class TestLengthComment:
    def test_positive_normal(self):
        assert isinstance(get_comment(5.0), str)

    def test_positive_large(self):
        assert isinstance(get_comment(75.0), str)

    def test_negative_normal(self):
        assert isinstance(get_comment(-30.0), str)

    def test_negative_large(self):
        assert isinstance(get_comment(-200.0), str)

    def test_extreme_positive(self):
        assert isinstance(get_comment(5000.0), str)

    def test_extreme_negative(self):
        assert isinstance(get_comment(-5000.0), str)


# ═══════════════════════════════════════════════════════════════════════════
# _glue_growth
# ═══════════════════════════════════════════════════════════════════════════


class TestGlueGrowth:
    def test_positive_origin_grows_or_shrinks(self):
        for _ in range(20):
            val = _glue_growth(20.0)
            assert isinstance(val, float)
            assert -15 <= val <= 15

    def test_negative_origin_grows_or_shrinks(self):
        for _ in range(20):
            val = _glue_growth(-20.0)
            assert isinstance(val, float)
            assert -15 <= val <= 15

    def test_coefficient_scales_result(self, monkeypatch):
        monkeypatch.setattr(random, "choice", lambda seq: 0.5)
        v1 = _glue_growth(10.0, coefficient=2.0)
        v2 = _glue_growth(10.0, coefficient=1.0)
        assert abs(v1) == pytest.approx(abs(v2) * 2.0, rel=0.02)  # rounding to 2dp

    def test_growth_proportional_to_abs_origin(self, monkeypatch):
        """Larger abs(origin) → proportionally larger absolute change."""
        monkeypatch.setattr(random, "choice", lambda seq: 0.5)
        small = _glue_growth(10.0)
        large = _glue_growth(500.0)
        assert abs(large) > abs(small)


# ═══════════════════════════════════════════════════════════════════════════
# _apply_decay
# ═══════════════════════════════════════════════════════════════════════════


class TestApplyDecay:
    @pytest.fixture
    def cfg(self):
        return NiuNiuConfig()

    def test_high_positive_decays_toward_zero(self, cfg):
        result = _apply_decay(60.0, cfg)
        assert 0 <= result < 60.0

    def test_normal_positive_decays_slowly(self, cfg):
        result = _apply_decay(20.0, cfg)
        assert 0 <= result < 20.0

    def test_positive_never_goes_below_zero(self, cfg):
        result = _apply_decay(0.001, cfg)
        assert result >= 0.0

    def test_negative_length_becomes_more_negative_from_decay(self, cfg):
        """For negative lengths, decay pushes further negative (deeper)."""
        result = _apply_decay(-20.0, cfg)
        assert result <= -20.0

    def test_high_negative_decays_toward_zero(self, cfg):
        """For high negative lengths, decay moves toward zero (less negative)."""
        result = _apply_decay(-60.0, cfg)
        assert -60.0 < result < 0

# ═══════════════════════════════════════════════════════════════════════════
# NiuNiuStore — CRUD
# ═══════════════════════════════════════════════════════════════════════════


class TestNiuNiuStoreCRUD:
    def test_schema_creates_tables(self, store):
        with store.connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            names = {r["name"] for r in rows}
            assert "niuniu_users" in names
            assert "niuniu_records" in names

    def test_first_user_gets_10_length(self, store):
        length = store.register("first")
        assert length == 10.0

    def test_exists_true_after_register(self, store, uid_a):
        assert store.exists(uid_a) is True

    def test_exists_false_for_missing(self, store):
        assert store.exists("noone") is False

    def test_get_length(self, store, uid_a):
        assert isinstance(store.get_length(uid_a), float)

    def test_get_length_none_for_missing(self, store):
        assert store.get_length("noone") is None

    def test_unsubscribe_deletes_and_returns_old_length(self, store, uid_a):
        old = store.get_length(uid_a)
        result = store.unsubscribe(uid_a)
        assert result == old
        assert not store.exists(uid_a)

    def test_unsubscribe_missing_returns_none(self, store):
        assert store.unsubscribe("noone") is None

    def test_update_length_changes_value(self, store, uid_a):
        store.update_length(uid_a, 42.5)
        assert store.get_length(uid_a) == 42.5

    def test_count(self, store):
        assert store.count() == 0
        store.register("a")
        store.register("b")
        assert store.count() == 2

    def test_migration_adds_missing_columns(self, tmp_path: Path):
        import sqlite3
        db_path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE niuniu_users (uid TEXT PRIMARY KEY, length REAL DEFAULT 0,
                created_at TEXT, updated_at TEXT);
            CREATE TABLE niuniu_records (id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT, action TEXT, origin_length REAL, new_length REAL, created_at TEXT);
            """
        )
        conn.close()
        store = NiuNiuStore(db_path)
        with store.connect() as c:
            cols = {
                r["name"]
                for r in c.execute("PRAGMA table_info('niuniu_users')").fetchall()
            }
        assert "luck" in cols
        assert "fence_luck" in cols


# ═══════════════════════════════════════════════════════════════════════════
# NiuNiuStore — records
# ═══════════════════════════════════════════════════════════════════════════


class TestNiuNiuStoreRecords:
    def test_register_adds_record(self, store, uid_a):
        records = store.get_records(uid_a)
        assert len(records) >= 1
        assert records[0]["action"] == "register"
        assert records[0]["origin_length"] == 0.0
        assert records[0]["new_length"] > 0

    def test_unsubscribe_adds_record(self, store, uid_a):
        store.unsubscribe(uid_a)
        records = store.get_records(uid_a)
        assert records[0]["action"] == "unsubscribe"

    def test_get_records_respects_limit(self, store, uid_a):
        store._add_record(uid_a, "test1", 10.0, 12.0)
        store._add_record(uid_a, "test2", 12.0, 14.0)
        # register + 2 test records = 3 total
        assert len(store.get_records(uid_a, limit=2)) == 2
        assert len(store.get_records(uid_a, limit=10)) == 3

    def test_latest_record_time(self, store, uid_a):
        last = store.latest_record_time(uid_a, "register")
        assert last != "暂无记录"

    def test_latest_record_time_missing(self, store, uid_a):
        assert store.latest_record_time(uid_a, "gluing") == "暂无记录"


# ═══════════════════════════════════════════════════════════════════════════
# NiuNiuStore — rankings
# ═══════════════════════════════════════════════════════════════════════════


class TestNiuNiuStoreRankings:
    def _setup_users(self, store):
        store.register("a")
        store.register("b")
        store.register("c")
        store.update_length("a", 50.0)
        store.update_length("b", 25.0)
        store.update_length("c", -40.0)

    def test_rank_by_length_only_positives(self, store):
        self._setup_users(store)
        entries = store.rank_by_length()
        assert all(e["length"] > 0 for e in entries)
        assert entries[0]["length"] >= entries[-1]["length"]

    def test_rank_by_depth_only_negatives(self, store):
        self._setup_users(store)
        entries = store.rank_by_depth()
        assert all(e["length"] >= 0 for e in entries)
        assert entries[0]["length"] >= entries[-1]["length"]

    def test_rank_by_natural_includes_all(self, store):
        self._setup_users(store)
        entries = store.rank_by_natural()
        assert len(entries) == 3

    def test_rank_by_absolute_includes_all(self, store):
        self._setup_users(store)
        entries = store.rank_by_absolute()
        assert len(entries) == 3

    def test_rank_with_user_ids_filter(self, store):
        self._setup_users(store)
        entries = store.rank_by_natural(user_ids=["a", "c"])
        assert len(entries) == 2
        uids = {e["uid"] for e in entries}
        assert uids == {"a", "c"}

    def test_get_rank_position_natural(self, store):
        self._setup_users(store)
        assert store.get_rank_position("a", "natural") == 1
        assert store.get_rank_position("c", "natural") == 3

    def test_get_rank_position_length_excludes_negatives(self, store):
        self._setup_users(store)
        assert store.get_rank_position("c", "length") == -1

    def test_get_rank_position_depth_excludes_positives(self, store):
        self._setup_users(store)
        assert store.get_rank_position("a", "depth") == -1

    def test_get_rank_position_missing_user(self, store):
        assert store.get_rank_position("nope", "natural") == -1


# ═══════════════════════════════════════════════════════════════════════════
# NiuNiuStore — luck
# ═══════════════════════════════════════════════════════════════════════════


class TestNiuNiuStoreLuck:
    def test_glue_luck_positive(self, store, uid_a):
        assert store.get_glue_luck(uid_a) > 0

    def test_set_glue_luck_overrides(self, store, uid_a):
        store.set_glue_luck(uid_a, 2.5)
        assert store.get_glue_luck(uid_a) == 2.5

    def test_fence_luck_positive(self, store, uid_a):
        assert store.get_fence_luck(uid_a) > 0

    def test_set_fence_luck_overrides(self, store, uid_a):
        store.set_fence_luck(uid_a, 3.0)
        assert store.get_fence_luck(uid_a) == 3.0

    def test_luck_re_rolls_daily(self, store, uid_a, monkeypatch):
        store.set_glue_luck(uid_a, 5.0)
        monkeypatch.setattr(store, "_today_str", lambda: "2099-01-01")
        assert store.get_glue_luck(uid_a) != 5.0

    def test_luck_default_for_unregistered(self, store):
        assert store.get_glue_luck("nobody") == 1.0
        assert store.get_fence_luck("nobody") == 1.0


# ═══════════════════════════════════════════════════════════════════════════
# gluing
# ═══════════════════════════════════════════════════════════════════════════


class TestGluing:
    def test_no_niuniu_returns_error(self, store):
        msg, length = gluing(store, "noone", group_id="test")
        assert "没有牛牛" in msg
        assert length == 0.0

    def test_arrested_returns_error(self, store, uid_a):
        arrested_cd.set(uid_a, 999)
        msg, _ = gluing(store, uid_a, group_id="test")
        assert "小黑屋" in msg

    def test_gluing_sets_cd(self, store, uid_a, monkeypatch):
        _patch_glue_event(monkeypatch, "normal")
        gluing(store, uid_a, group_id="test")
        assert glue_cd.check(uid_a) > 0

    def test_gluing_adds_record(self, store, uid_a, monkeypatch):
        _patch_glue_event(monkeypatch, "normal")
        gluing(store, uid_a, group_id="test")
        records = store.get_records(uid_a)
        assert records[0]["action"] == "gluing"

    def test_gluing_changes_length(self, store, uid_a, monkeypatch):
        old_len = store.get_length(uid_a)
        _patch_glue_event(monkeypatch, "normal")
        _, new_len = gluing(store, uid_a, group_id="test")
        assert new_len != old_len

    def test_mirror_flips_positive_to_negative(self, store, uid_a, monkeypatch):
        store.update_length(uid_a, 20.0)
        _patch_glue_event(monkeypatch, "mirror")
        _, new_len = gluing(store, uid_a, group_id="test")
        assert new_len == pytest.approx(-20.0, abs=1.0)

    def test_mirror_too_short_near_zero(self, store, uid_a, monkeypatch):
        store.update_length(uid_a, 0.0)
        _patch_glue_event(monkeypatch, "mirror")
        msg, new_len = gluing(store, uid_a, group_id="test")
        assert "太短" in msg
        assert new_len == 0.0

    def test_arrested_event_blocks(self, store, uid_a, monkeypatch):
        store.update_length(uid_a, 20.0)
        _patch_glue_event(monkeypatch, "arrested")
        msg, new_len = gluing(store, uid_a, group_id="test")
        assert "小黑屋" in msg
        assert arrested_cd.check(uid_a) > 0
        assert new_len == pytest.approx(20.0, abs=1.0)

    def test_shrinkage_reduces_length(self, store, uid_a, monkeypatch):
        store.update_length(uid_a, 30.0)
        _patch_glue_event(monkeypatch, "shrinkage")
        msg, new_len = gluing(store, uid_a, group_id="test")
        assert isinstance(msg, str)
        assert new_len <= 30.0

    def test_blessing_increases_length(self, store, uid_a, monkeypatch):
        store.update_length(uid_a, 20.0)
        store.set_glue_luck(uid_a, 2.0)  # double effect
        _patch_glue_event(monkeypatch, "blessing")
        _patch_uniform(monkeypatch, 10.0)
        _, new_len = gluing(store, uid_a, group_id="test")
        assert new_len > 20.0

    def test_luck_multiplier_affects_result(self, store, uid_a, monkeypatch):
        store.update_length(uid_a, 20.0)
        store.set_glue_luck(uid_a, 100.0)
        _patch_glue_event(monkeypatch, "blessing")
        _patch_uniform(monkeypatch, 5.0)
        _, new_len = gluing(store, uid_a, group_id="test")
        assert new_len > 50.0

    def test_decay_applied_after_gluing_high_length(self, store, uid_a, monkeypatch):
        store.update_length(uid_a, 500.0)
        store.set_glue_luck(uid_a, 0.01)  # lowest luck → massive shrinkage
        _patch_glue_event(monkeypatch, "blessing")
        _patch_uniform(monkeypatch, 5.0)
        _, new_len = gluing(store, uid_a, group_id="test")
        assert new_len < 500.0


# ═══════════════════════════════════════════════════════════════════════════
# _fence_win_prob
# ═══════════════════════════════════════════════════════════════════════════


class TestFenceWinProb:
    def test_zero_lengths_return_fifty(self):
        assert _fence_win_prob(0.0, 0.0) == 0.5

    def test_equal_lengths_gives_base_probability(self):
        """Equal abs lengths give the base 0.85 probability (no reduction)."""
        p = _fence_win_prob(30.0, 30.0)
        assert p == pytest.approx(0.85)

    def test_symmetric_for_equal_abs(self):
        """Function is symmetric: only ratio and sign matter, not order."""
        assert _fence_win_prob(80.0, 20.0) == _fence_win_prob(20.0, 80.0)

    def test_negative_inverts_probability(self):
        p_pos = _fence_win_prob(50.0, 10.0)
        p_neg = _fence_win_prob(-50.0, 10.0)
        assert p_pos > 0.5
        assert p_neg < 0.5

    def test_within_bounds(self):
        for _ in range(100):
            a = random.uniform(-200, 200)
            b = random.uniform(-200, 200)
            p = _fence_win_prob(a, b)
            assert 0.05 <= p <= 0.85


# ═══════════════════════════════════════════════════════════════════════════
# _fence_winner_is_role
# ═══════════════════════════════════════════════════════════════════════════


class TestFenceWinnerIsRole:
    @pytest.fixture
    def cfg(self):
        return NiuNiuConfig()

    def test_winner_is_niutouren(self, cfg):
        assert _fence_winner_is_role(True, 60.0, 10.0, "niutouren", cfg) is True

    def test_winner_not_niutouren(self, cfg):
        assert _fence_winner_is_role(True, 10.0, 10.0, "niutouren", cfg) is False

    def test_defender_niutouren_attacker_loses(self, cfg):
        assert _fence_winner_is_role(False, 10.0, 60.0, "niutouren", cfg) is True

    def test_winner_is_succubus(self, cfg):
        assert _fence_winner_is_role(True, -60.0, 10.0, "succubus", cfg) is True

    def test_winner_not_succubus_positive(self, cfg):
        assert _fence_winner_is_role(True, 40.0, -10.0, "succubus", cfg) is False

    def test_defender_succubus_attacker_loses(self, cfg):
        assert _fence_winner_is_role(False, 10.0, -60.0, "succubus", cfg) is True


# ═══════════════════════════════════════════════════════════════════════════
# fencing
# ═══════════════════════════════════════════════════════════════════════════


class TestFencing:
    def test_no_niuniu_attacker(self, store):
        assert "没有牛牛" in fencing(store, "noone", "someone", group_id="test")

    def test_target_no_niuniu_reject(self, store, uid_a, monkeypatch):
        _patch_no_niuniu_event(monkeypatch, "reject")
        result = fencing(store, uid_a, "noone", group_id="test")
        assert "对方" in result or "空气" in result or "无敌" in result

    def test_target_no_niuniu_self_hurt(self, store, uid_a, monkeypatch):
        _patch_no_niuniu_event(monkeypatch, "self_hurt")
        assert isinstance(fencing(store, uid_a, "noone", group_id="test"), str)

    def test_force_register_then_fence(self, store, uid_a, monkeypatch):
        """force_register creates opponent then proceeds to real fencing."""
        events = iter(
            [
                next(e for e in NO_NIUNIU_EVENTS if e["name"] == "force_register"),
                _normal_fence_event(),
            ]
        )
        monkeypatch.setattr(
            random, "choices", lambda population, weights=None, k=1: [next(events)]
        )
        result = fencing(store, uid_a, "noone", group_id="test")
        assert store.exists("noone")
        assert isinstance(result, str)

    def test_bot_gets_phantom_length(self, store, uid_a, monkeypatch):
        _patch_fence_event(monkeypatch, "normal")
        assert isinstance(fencing(store, uid_a, "bot_uid", oppo_is_bot=True, group_id="test"), str)

    def test_fencing_sets_attacker_cd(self, store, uid_a, uid_b, monkeypatch):
        _patch_fence_event(monkeypatch, "normal")
        fencing(store, uid_a, uid_b, group_id="test")
        assert fence_cd.check(uid_a) > 0

    def test_fencing_sets_defender_cd(self, store, uid_a, uid_b, monkeypatch):
        _patch_fence_event(monkeypatch, "normal")
        fencing(store, uid_a, uid_b, group_id="test")
        assert fenced_cd.check(uid_b) > 0

    def test_fencing_adds_records(self, store, uid_a, uid_b, monkeypatch):
        _patch_fence_event(monkeypatch, "normal")
        fencing(store, uid_a, uid_b, group_id="test")
        a_recs = store.get_records(uid_a)
        b_recs = store.get_records(uid_b)
        assert any(r["action"] == "fencing" for r in a_recs)
        assert any(r["action"] == "fenced" for r in b_recs)

    def test_draw_damages_both(self, store, uid_a, uid_b, monkeypatch):
        store.update_length(uid_a, 20.0)
        store.update_length(uid_b, 20.0)
        _patch_fence_event(monkeypatch, "draw")
        fencing(store, uid_a, uid_b, group_id="test")
        assert store.get_length(uid_a) < 20.0
        assert store.get_length(uid_b) < 20.0

    def test_dominate_downgrades_when_winner_not_niutouren(
        self, store, uid_a, uid_b, monkeypatch
    ):
        """Neither player is 牛头人 → dominate downgrades to normal."""
        store.update_length(uid_a, 10.0)
        store.update_length(uid_b, 15.0)
        _patch_fence_event(monkeypatch, "dominate")
        result = fencing(store, uid_a, uid_b, group_id="test")
        assert isinstance(result, str)

    def test_succubus_downgrades_when_winner_not_succubus(
        self, store, uid_a, uid_b, monkeypatch
    ):
        """Both players are positive → succubus downgrades to normal."""
        store.update_length(uid_a, 10.0)
        store.update_length(uid_b, 20.0)
        _patch_fence_event(monkeypatch, "succubus_devour")
        result = fencing(store, uid_a, uid_b, group_id="test")
        assert isinstance(result, str)

    def test_dominate_sever_for_niutouren(self, store, uid_a, uid_b, monkeypatch):
        """牛头人 winner can trigger sever (腰斩)."""
        store.update_length(uid_a, 80.0)
        store.update_length(uid_b, 10.0)
        _patch_fence_event(monkeypatch, "dominate")
        monkeypatch.setattr(random, "random", lambda: 0.0)
        result = fencing(store, uid_a, uid_b, group_id="test")
        assert any(
            kw in result for kw in ("腰斩", "处刑", "断头台", "支配")
        ), f"Expected sever message, got: {result}"

    def test_succubus_devour_for_succubus(self, store, uid_a, uid_b, monkeypatch):
        """魅魔 winner triggers devour (吞噬). Ensure succubus wins."""
        store.update_length(uid_a, -50.0)
        store.update_length(uid_b, 20.0)
        store.set_fence_luck(uid_a, 100.0)  # guarantee win
        _patch_fence_event(monkeypatch, "succubus_devour")
        _patch_random(monkeypatch, 0.0)  # win_prob check passes
        result = fencing(store, uid_a, uid_b, group_id="test")
        assert "吞噬" in result or "魅魔" in result

    def test_reversal_flips_winner(self, store, uid_a, uid_b, monkeypatch):
        store.update_length(uid_a, 10.0)
        store.update_length(uid_b, 100.0)
        _patch_fence_event(monkeypatch, "reversal")
        assert isinstance(fencing(store, uid_a, uid_b, group_id="test"), str)

    def test_slip_attacker_always_loses(self, store, uid_a, uid_b, monkeypatch):
        store.update_length(uid_a, 200.0)
        store.update_length(uid_b, 1.0)
        _patch_fence_event(monkeypatch, "slip")
        fencing(store, uid_a, uid_b, group_id="test")
        assert store.get_length(uid_a) < 200.0

    def test_critical_multiplies_damage(self, store, uid_a, uid_b, monkeypatch):
        store.update_length(uid_a, 30.0)
        store.update_length(uid_b, 30.0)
        _patch_fence_event(monkeypatch, "critical")
        assert isinstance(fencing(store, uid_a, uid_b, group_id="test"), str)

    def test_bot_fencing_no_defender_db_write(self, store, uid_a, monkeypatch):
        _patch_fence_event(monkeypatch, "normal")
        fencing(store, uid_a, "bot", oppo_is_bot=True, group_id="test")
        assert not store.exists("bot")

    def test_fence_luck_sways_outcome(self, store, uid_a, uid_b, monkeypatch):
        store.update_length(uid_a, 20.0)
        store.update_length(uid_b, 20.0)
        store.set_fence_luck(uid_a, 100.0)
        _patch_fence_event(monkeypatch, "normal")
        assert isinstance(fencing(store, uid_a, uid_b, group_id="test"), str)


# ═══════════════════════════════════════════════════════════════════════════
# Event data integrity
# ═══════════════════════════════════════════════════════════════════════════


class TestEventDataIntegrity:
    def test_glue_events_have_name_and_weight(self):
        for e in GLUE_EVENTS:
            assert "name" in e and "weight" in e

    def test_fence_events_have_name_and_weight(self):
        for e in FENCE_EVENTS:
            assert "name" in e and "weight" in e

    def test_dominate_has_require_role(self):
        e = next(e for e in FENCE_EVENTS if e["name"] == "dominate")
        assert e.get("require_role") == "niutouren"

    def test_succubus_has_require_role(self):
        e = next(e for e in FENCE_EVENTS if e["name"] == "succubus_devour")
        assert e.get("require_role") == "succubus"

    def test_no_niuniu_events_have_name_and_weight(self):
        for e in NO_NIUNIU_EVENTS:
            assert "name" in e and "weight" in e

    def test_normal_fence_event_has_no_require_role(self):
        assert "require_role" not in _normal_fence_event()
