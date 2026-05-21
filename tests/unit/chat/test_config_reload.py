from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from quickquip.chat import config as chat_config
from quickquip.chat import context_rules as context_rules_module
from quickquip.chat import rule_switch as rule_switch_module
from quickquip.chat import text_rules as text_rules_module
from quickquip.chat.text_rules import match_text_rule


@contextmanager
def _chdir(path: Path):
    prev = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


@pytest.fixture
def restore_chat_rules():
    """Snapshot + restore module-level chat rule state so tests stay isolated."""
    text_snapshot = list(chat_config.TEXT_REPLY_RULES)
    ctx_snapshot = list(chat_config.CONTEXT_REPLY_RULES)
    chain_snapshot = list(chat_config.CHAIN_GAME_CONFIGS)
    rate_snapshot = dict(chat_config.RATE_LIMIT_RULES)
    switchable_snapshot = set(rule_switch_module.SWITCHABLE_RULES)
    try:
        yield
    finally:
        chat_config.TEXT_REPLY_RULES[:] = text_snapshot
        chat_config.CONTEXT_REPLY_RULES[:] = ctx_snapshot
        chat_config.CHAIN_GAME_CONFIGS[:] = chain_snapshot
        chat_config.RATE_LIMIT_RULES.clear()
        chat_config.RATE_LIMIT_RULES.update(rate_snapshot)
        rule_switch_module.SWITCHABLE_RULES.clear()
        rule_switch_module.SWITCHABLE_RULES.update(switchable_snapshot)
        text_rules_module.recompile_patterns()
        context_rules_module.recompile_patterns()


def test_reload_missing_toml_keeps_builtins(tmp_path: Path, restore_chat_rules):
    (tmp_path / "config").mkdir()
    with _chdir(tmp_path):
        chat_config.reload_chat_rules()
    assert chat_config.TEXT_REPLY_RULES == []
    assert chat_config.CONTEXT_REPLY_RULES == []
    assert chat_config.CHAIN_GAME_CONFIGS == []
    # built-ins remain intact
    assert "llm_chat" in chat_config.RATE_LIMIT_RULES
    assert "timezone_wake" in chat_config.RATE_LIMIT_RULES


def test_reload_idempotent_does_not_double_insert(tmp_path: Path, restore_chat_rules):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "chat_rules.toml").write_text(
        """
[rate_limit_rules]
greeting = {global_limit = 3, user_limit = 1}

[[rules]]
name = 'greeting'
patterns = ['^你好$']
reply_template = 'hi'
rate_limit_key = 'greeting'
priority = 10
""",
        encoding="utf-8",
    )
    with _chdir(tmp_path):
        chat_config.reload_chat_rules()
        chat_config.reload_chat_rules()
        chat_config.reload_chat_rules()
    assert len(chat_config.TEXT_REPLY_RULES) == 1
    assert chat_config.RATE_LIMIT_RULES["greeting"] == {"global_limit": 3, "user_limit": 1}
    # builtin not clobbered
    assert chat_config.RATE_LIMIT_RULES["llm_chat"]["scope"] == "global"


def test_reload_malformed_toml_preserves_state(tmp_path: Path, restore_chat_rules):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "chat_rules.toml").write_text(
        """
[[rules]]
name = 'ok'
patterns = ['^你好$']
reply_template = 'hi'
rate_limit_key = 'greeting'
priority = 10
""",
        encoding="utf-8",
    )
    with _chdir(tmp_path):
        chat_config.reload_chat_rules()
    assert len(chat_config.TEXT_REPLY_RULES) == 1

    (config_dir / "chat_rules.toml").write_text("this is not valid toml [[", encoding="utf-8")
    with _chdir(tmp_path):
        ok = chat_config.reload_chat_rules()
    assert ok is False  # malformed TOML returns False, does not raise
    # state untouched after failure
    assert len(chat_config.TEXT_REPLY_RULES) == 1
    assert chat_config.TEXT_REPLY_RULES[0]["name"] == "ok"


def test_recompile_patterns_reflects_new_rules(tmp_path: Path, restore_chat_rules):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "chat_rules.toml").write_text(
        """
[rate_limit_rules]
pre = {global_limit = 6, user_limit = 3}

[[rules]]
name = 'pre_only'
patterns = ['^ping$']
reply_template = 'pong'
rate_limit_key = 'pre'
priority = 10
""",
        encoding="utf-8",
    )
    with _chdir(tmp_path):
        chat_config.reload_chat_rules()
        text_rules_module.recompile_patterns()
    assert match_text_rule("ping", user_id=1, sender_name="u")["rule_name"] == "pre_only"

    (config_dir / "chat_rules.toml").write_text(
        """
[rate_limit_rules]
post = {global_limit = 6, user_limit = 3}

[[rules]]
name = 'post_only'
patterns = ['^hello$']
reply_template = 'world'
rate_limit_key = 'post'
priority = 10
""",
        encoding="utf-8",
    )
    with _chdir(tmp_path):
        chat_config.reload_chat_rules()
        text_rules_module.recompile_patterns()

    # old pattern gone, new pattern wins
    assert match_text_rule("ping", user_id=1, sender_name="u") is None
    assert match_text_rule("hello", user_id=1, sender_name="u")["rule_name"] == "post_only"


def test_rebuild_switchable_rules_includes_toml_names(tmp_path: Path, restore_chat_rules):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "chat_rules.toml").write_text(
        """
[rate_limit_rules]
swap = {global_limit = 6, user_limit = 3}

[[rules]]
name = 'new_rule_xyz'
patterns = ['^swap$']
reply_template = 'ok'
rate_limit_key = 'swap'
priority = 10
""",
        encoding="utf-8",
    )
    with _chdir(tmp_path):
        chat_config.reload_chat_rules()
        rule_switch_module.rebuild_switchable_rules()
    assert "new_rule_xyz" in rule_switch_module.SWITCHABLE_RULES
    # builtins preserved
    assert "llm_chat" in rule_switch_module.SWITCHABLE_RULES
