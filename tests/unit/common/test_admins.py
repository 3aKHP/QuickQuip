"""全局管理员身份单测：角色矩阵、热重载、坏配置容错、审计与委托链回归。"""

from __future__ import annotations

import json
import os

import pytest

from quickquip.common import admins
from quickquip.common.admins import (
    AdminRegistry,
    ActorRole,
    actor_role,
    check_admin_authority,
    configure,
    has_admin_authority,
    reset,
)

_ADMIN = "1000000000"
_OTHER = "1000000001"
_GROUP_ID = "123456789"


class _Sender:
    def __init__(self, role=None):
        self.role = role


class _Event:
    def __init__(self, user_id, role=None, group_id=_GROUP_ID):
        self.user_id = user_id
        self.sender = _Sender(role) if role is not None else None
        self.group_id = group_id


class _FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, dt):
        self.now += dt


def _write(path, qq_list):
    body = "global_admins = [\n" + "".join(f'    "{q}",\n' for q in qq_list) + "]\n"
    path.write_text(body, encoding="utf-8")


def _bump_mtime(path, tick):
    """显式设置 mtime，避开文件系统时间戳精度差异导致的重载抖动。"""
    os.utime(path, ns=(tick, tick))


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    """默认注册表指向保证不存在的路径，隔离开发机上的真实 config。"""
    configure(tmp_path / "absent.toml")
    yield
    reset()


@pytest.fixture
def admin_trace(monkeypatch):
    records: list[str] = []

    class _Cap:
        def info(self, message):
            records.append(message)

    monkeypatch.setattr(admins, "_logger", _Cap())
    return records


def _trace_payloads(records):
    out = []
    for line in records:
        if line.startswith("ADMIN_TRACE "):
            out.append(json.loads(line[len("ADMIN_TRACE "):]))
    return out


# ── 角色解析 ─────────────────────────────────────────────────────────────────


def test_actor_role_matrix(tmp_path):
    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    configure(path)

    assert actor_role(_Event(_ADMIN, role=None)) is ActorRole.GLOBAL_ADMIN
    assert actor_role(_Event(_OTHER, role="owner")) is ActorRole.GROUP_OWNER
    assert actor_role(_Event(_OTHER, role="admin")) is ActorRole.GROUP_ADMIN
    assert actor_role(_Event(_OTHER, role=None)) is ActorRole.MEMBER
    assert actor_role(_Event(_OTHER, role="member")) is ActorRole.MEMBER


def test_dual_identity_resolves_global(tmp_path):
    """既是群管理又是全局管理时视作后者。"""
    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    configure(path)

    assert actor_role(_Event(_ADMIN, role="admin")) is ActorRole.GLOBAL_ADMIN
    assert actor_role(_Event(_ADMIN, role="owner")) is ActorRole.GLOBAL_ADMIN


def test_private_event_resolves_member_even_if_registered(tmp_path):
    """私聊（group_id 缺失）不放行：注册表命中也恒 MEMBER。"""
    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    configure(path)

    assert actor_role(_Event(_ADMIN, role=None, group_id=None)) is ActorRole.MEMBER
    assert has_admin_authority(_Event(_ADMIN, role=None, group_id=None)) is False


def test_foreign_group_global_admin_passes_is_admin(tmp_path):
    """等价性验收：无群角色的全局管理员通过既有管理员门禁。"""
    from quickquip.common.event_utils import is_admin

    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    configure(path)

    assert is_admin(_Event(_ADMIN, role=None)) is True
    assert is_admin(_Event(_OTHER, role="member")) is False
    assert is_admin(_Event(_OTHER, role="admin")) is True
    assert is_admin(_Event(_OTHER, role="owner")) is True


def test_command_parts_shim_inherits_global_admin(tmp_path):
    """回归：command_parts 垫片链导入的 _is_admin 同样继承新语义。"""
    from quickquip.adapters.nonebot.command_parts.common import _is_admin

    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    configure(path)

    assert _is_admin(_Event(_ADMIN, role=None)) is True
    assert _is_admin(_Event(_OTHER, role="member")) is False


# ── 注册表：热重载与容错 ─────────────────────────────────────────────────────


def test_hot_reload_add_and_remove(tmp_path):
    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    _bump_mtime(path, 10**9)
    clock = _FakeClock()
    registry = AdminRegistry(path, clock=clock)
    assert registry.contains(_ADMIN)

    _write(path, [_OTHER])
    _bump_mtime(path, 2 * 10**9)
    clock.advance(1)
    assert registry.contains(_ADMIN)
    assert not registry.contains(_OTHER)

    clock.advance(10)
    assert registry.contains(_OTHER)
    assert not registry.contains(_ADMIN)


def test_corrupt_file_keeps_last_valid(tmp_path):
    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    _bump_mtime(path, 10**9)
    clock = _FakeClock()
    registry = AdminRegistry(path, clock=clock)
    assert registry.contains(_ADMIN)

    path.write_text("global_admins = [broken", encoding="utf-8")
    _bump_mtime(path, 2 * 10**9)
    clock.advance(10)
    assert registry.contains(_ADMIN)


def test_missing_file_is_empty_registry(tmp_path):
    registry = AdminRegistry(tmp_path / "absent.toml", clock=_FakeClock())
    assert registry.snapshot() == frozenset()


def test_empty_list_is_closed_state(tmp_path, admin_trace):
    path = tmp_path / "admins.toml"
    path.write_text("global_admins = []\n", encoding="utf-8")
    registry = AdminRegistry(path, clock=_FakeClock())
    assert registry.snapshot() == frozenset()
    assert _trace_payloads(admin_trace) == [
        {"kind": "registry_loaded", "count": 0, "admins": []}
    ]


def test_ttl_expired_stamp_unchanged_no_reread(tmp_path, admin_trace):
    """TTL 到期但 mtime/size 未变：跳过重读，不产生新审计行。"""
    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    _bump_mtime(path, 10**9)
    clock = _FakeClock()
    registry = AdminRegistry(path, clock=clock)
    assert registry.contains(_ADMIN)

    clock.advance(10)
    assert registry.snapshot() == frozenset({_ADMIN})
    assert len(_trace_payloads(admin_trace)) == 1


def test_deletion_after_load_clears_and_audits(tmp_path, admin_trace):
    """有名单后删除文件：清空为关闭态并记 registry_loaded count=0。"""
    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    _bump_mtime(path, 10**9)
    clock = _FakeClock()
    registry = AdminRegistry(path, clock=clock)
    assert registry.contains(_ADMIN)

    path.unlink()
    clock.advance(10)
    assert registry.snapshot() == frozenset()
    payloads = _trace_payloads(admin_trace)
    assert payloads[-1] == {"kind": "registry_loaded", "count": 0, "admins": []}


def test_int_user_id_hits_registry(tmp_path):
    """生产 OneBot v11 事件的 user_id 是 int；int 形态同样命中注册表。"""
    path = tmp_path / "admins.toml"
    _write(path, ["1000000000"])
    configure(path)

    assert actor_role(_Event(1000000000, role=None)) is ActorRole.GLOBAL_ADMIN


def test_invalid_entries_skipped(tmp_path):
    path = tmp_path / "admins.toml"
    path.write_text(
        f'global_admins = ["{_ADMIN}", "abc", "", "0755"]', encoding="utf-8"
    )
    registry = AdminRegistry(path, clock=_FakeClock())
    assert registry.snapshot() == frozenset({_ADMIN})


def test_not_a_list_keeps_last_valid(tmp_path):
    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    _bump_mtime(path, 10**9)
    clock = _FakeClock()
    registry = AdminRegistry(path, clock=clock)
    assert registry.contains(_ADMIN)

    path.write_text('global_admins = "1000000000"', encoding="utf-8")
    _bump_mtime(path, 2 * 10**9)
    clock.advance(10)
    assert registry.snapshot() == frozenset({_ADMIN})


# ── 审计 ─────────────────────────────────────────────────────────────────────


def test_registry_loaded_audit(tmp_path, admin_trace):
    path = tmp_path / "admins.toml"
    _write(path, [_OTHER, _ADMIN])
    _bump_mtime(path, 10**9)
    registry = AdminRegistry(path, clock=_FakeClock())
    registry.snapshot()

    payloads = _trace_payloads(admin_trace)
    assert payloads == [
        {
            "kind": "registry_loaded",
            "count": 2,
            "admins": [_ADMIN, _OTHER],
        }
    ]


def test_registry_loaded_audit_on_reload_change(tmp_path, admin_trace):
    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    _bump_mtime(path, 10**9)
    clock = _FakeClock()
    registry = AdminRegistry(path, clock=clock)
    registry.snapshot()

    _write(path, [_ADMIN, _OTHER])
    _bump_mtime(path, 2 * 10**9)
    clock.advance(10)
    registry.snapshot()

    kinds = [p["kind"] for p in _trace_payloads(admin_trace)]
    assert kinds == ["registry_loaded", "registry_loaded"]
    assert _trace_payloads(admin_trace)[-1]["count"] == 2


def test_query_predicate_is_side_effect_free(tmp_path, admin_trace):
    """纯查询谓词不产生审计；门禁入口才记 global_admin_unlock。"""
    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    configure(path)

    assert has_admin_authority(_Event(_ADMIN, role=None)) is True
    # 首查触发的 registry_loaded 属注册表自身留痕，与权限查询无关
    assert [p for p in _trace_payloads(admin_trace) if p["kind"] == "global_admin_unlock"] == []

    check_admin_authority(_Event(_ADMIN, role=None))
    unlocks = [p for p in _trace_payloads(admin_trace) if p["kind"] == "global_admin_unlock"]
    assert len(unlocks) == 1


def test_global_unlock_audit_only_when_load_bearing(tmp_path, admin_trace):
    path = tmp_path / "admins.toml"
    _write(path, [_ADMIN])
    configure(path)

    check_admin_authority(_Event(_ADMIN, role=None))
    check_admin_authority(_Event(_ADMIN, role="admin"))
    check_admin_authority(_Event(_OTHER, role="admin"))
    assert check_admin_authority(_Event(_OTHER, role=None)) is False

    unlocks = [p for p in _trace_payloads(admin_trace) if p["kind"] == "global_admin_unlock"]
    assert len(unlocks) == 1
    assert unlocks[0]["user_id"] == _ADMIN
    assert unlocks[0]["group_id"] == _GROUP_ID
    assert unlocks[0]["ts"] > 0
