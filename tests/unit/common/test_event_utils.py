"""Tests for quickquip.common.event_utils — pure event-inspection helpers."""
from __future__ import annotations

from types import SimpleNamespace

from quickquip.common.event_utils import (
    get_sender_name,
    is_admin,
    is_self_message,
    strip_command_name,
)


# ── get_sender_name ────────────────────────────────────────────────

def test_get_sender_name_prefers_card():
    event = SimpleNamespace(sender=SimpleNamespace(card="群名片", nickname="昵称"), user_id=1001)
    assert get_sender_name(event) == "群名片"


def test_get_sender_name_falls_back_to_nickname():
    event = SimpleNamespace(sender=SimpleNamespace(card=None, nickname="昵称"), user_id=1001)
    assert get_sender_name(event) == "昵称"


def test_get_sender_name_falls_back_to_user_id_when_no_sender():
    event = SimpleNamespace(user_id=1001)
    assert get_sender_name(event) == "1001"


def test_get_sender_name_falls_back_to_user_id_when_sender_empty():
    event = SimpleNamespace(sender=SimpleNamespace(card=None, nickname=None), user_id=1001)
    assert get_sender_name(event) == "1001"


# ── is_admin ───────────────────────────────────────────────────────

def test_is_admin_admin_role():
    event = SimpleNamespace(sender=SimpleNamespace(role="admin"))
    assert is_admin(event) is True


def test_is_admin_owner_role():
    event = SimpleNamespace(sender=SimpleNamespace(role="owner"))
    assert is_admin(event) is True


def test_is_admin_member_role():
    event = SimpleNamespace(sender=SimpleNamespace(role="member"))
    assert is_admin(event) is False


def test_is_admin_no_role_attribute():
    event = SimpleNamespace(sender=SimpleNamespace())
    assert is_admin(event) is False


def test_is_admin_no_sender():
    event = SimpleNamespace()
    assert is_admin(event) is False


# ── is_self_message ────────────────────────────────────────────────

def test_is_self_message_equal_ids():
    event = SimpleNamespace(user_id=10001, self_id=10001)
    assert is_self_message(event) is True


def test_is_self_message_different_ids():
    event = SimpleNamespace(user_id=10001, self_id=10002)
    assert is_self_message(event) is False


def test_is_self_message_int_str_mix():
    event = SimpleNamespace(user_id=10001, self_id="10001")
    assert is_self_message(event) is True


# ── strip_command_name ─────────────────────────────────────────────

def test_strip_slash_prefix():
    assert strip_command_name("/awakening on", "awakening") == "on"


def test_strip_bang_prefix():
    assert strip_command_name("!awakening off", "awakening") == "off"


def test_strip_bare_prefix():
    assert strip_command_name("awakening status", "awakening") == "status"


def test_strip_no_match_returns_original():
    assert strip_command_name("hello world", "awakening") == "hello world"


def test_strip_handles_whitespace():
    assert strip_command_name("  /awakening   on  ", "awakening") == "on"
