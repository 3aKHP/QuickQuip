from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier
from uuid import UUID

import pytest

from quickquip.llm.session import SessionInvalidated, SessionStoreError, create_session_identity
from quickquip.llm.store import LLMStore


def test_identity_is_immutable_random_and_utc():
    identity = create_session_identity()
    assert UUID(identity.id).version == 4
    assert identity.created_at.utcoffset().total_seconds() == 0
    assert create_session_identity().id != identity.id
    with pytest.raises(FrozenInstanceError):
        identity.id = "changed"


def test_binding_is_shared_within_scope_isolated_and_survives_restart(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    identity, generation = store.get_or_create_chat_session("10")
    assert store.get_or_create_chat_session("10") == (identity, generation)
    assert store.get_or_create_chat_session("private:10")[0] != identity
    assert store.get_or_create_chat_session("11")[0] != identity
    assert LLMStore(store.path).get_or_create_chat_session("10") == (identity, generation)


def test_concurrent_first_allocation_is_one_identity(tmp_path):
    stores = [LLMStore(tmp_path / "chat.db") for _ in range(4)]
    barrier = Barrier(len(stores))

    def allocate(store):
        barrier.wait(timeout=5)
        return store.get_or_create_chat_session("group")

    with ThreadPoolExecutor(max_workers=len(stores)) as executor:
        results = list(executor.map(allocate, stores))
    assert all(result == results[0] for result in results)


def test_clear_rotates_even_empty_history_and_rejects_late_write(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    original, generation = store.get_or_create_chat_session("g")
    store.update_group_settings("g", model="m")
    store.add_memory("g", "persistent fact")
    assert store.clear_chat_session("g") == 0
    assert store.get_chat_session("g") is None
    replacement, new_generation = store.get_or_create_chat_session("g")
    assert replacement != original
    assert new_generation > generation
    with pytest.raises(SessionInvalidated):
        store.append_session_reply(
            "g", original, generation, user_message=None, assistant_text="late",
        )
    assert store.count_conversation_messages("g") == 0
    assert store.get_group_settings("g").model == "m"
    assert store.count_memories("g") == 1


def test_archive_preserves_identity_and_resume_replaces_current(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    original = store.start_private_chat_session("u")
    generation, _ = store.agent_scope_state("private:u")
    store.append_session_reply(
        "private:u", original, generation, user_message=None, assistant_text="saved",
    )
    archived = store.end_private_chat_session("u", save=True, persona_id="p", preset="preset")
    assert archived == {"deleted": 1, "archive_number": 1}
    assert store.get_chat_session("private:u") is None
    assert store.get_group_settings("private:u").enabled is False
    replacement = store.start_private_chat_session("u")
    assert replacement != original
    restored = store.resume_private_chat_session("u", 1)
    assert restored["preset"] == "preset"
    assert store.get_chat_session("private:u") == original
    assert store.get_group_settings("private:u").enabled is True
    assert store.list_recent_conversation_messages("private:u", 10)[0]["content"] == "saved"
    assert store.get_session_archive("u", 1) is None


def test_empty_private_session_ends_without_archive_and_missing_resume_is_non_destructive(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    original = store.start_private_chat_session("u")
    assert "error" in store.resume_private_chat_session("u", 99)
    assert store.get_chat_session("private:u") == original
    assert store.get_group_settings("private:u").enabled is True
    assert store.end_private_chat_session("u", save=True, persona_id=None, preset="") == {
        "deleted": 0, "archive_number": None,
    }
    assert store.get_chat_session("private:u") is None


def test_clear_failure_rolls_back_messages_identity_and_generation(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    identity, generation = store.get_or_create_chat_session("g")
    store.append_session_reply("g", identity, generation, user_message=None, assistant_text="keep")
    with store._connect() as conn:
        conn.execute(
            "CREATE TRIGGER fail_clear BEFORE UPDATE OF session_id ON agent_scopes "
            "WHEN NEW.session_id IS NULL BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(SessionStoreError):
        store.clear_chat_session("g")
    assert store.get_or_create_chat_session("g") == (identity, generation)
    assert store.count_conversation_messages("g") == 1


def test_archive_failure_rolls_back_all_transition_state(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    identity = store.start_private_chat_session("u")
    generation, _ = store.agent_scope_state("private:u")
    store.append_session_reply(
        "private:u", identity, generation, user_message=None, assistant_text="keep",
    )
    with store._connect() as conn:
        conn.execute(
            "CREATE TRIGGER fail_end BEFORE UPDATE OF enabled ON group_settings "
            "WHEN NEW.enabled = 0 BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(SessionStoreError):
        store.end_private_chat_session("u", save=True, persona_id=None, preset="")
    assert store.get_or_create_chat_session("private:u") == (identity, generation)
    assert store.count_conversation_messages("private:u") == 1
    assert store.list_session_archives("u") == []
    assert store.get_group_settings("private:u").enabled is True


def test_legacy_archive_allocates_identity_on_resume(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    store.append_conversation_message("private:u", "u", "user", "legacy")
    store.create_session_archive("u", 1, message_count=1)
    store.archive_conversation_messages("u", 1)
    store.resume_private_chat_session("u", 1)
    identity = store.get_chat_session("private:u")
    assert identity is not None
    assert store.list_recent_conversation_messages("private:u", 10)[0]["content"] == "legacy"
    assert LLMStore(store.path).get_chat_session("private:u") == identity


def test_v2_migration_is_additive_and_does_not_repeat_legacy_backfill(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    store.append_conversation_message("g", "u", "user", "not an agent loop")
    with store._connect() as conn:
        for table in ("agent_scopes", "session_archives"):
            for column in ("session_id", "session_created_at"):
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.execute("DELETE FROM agent_schema_migrations WHERE version = 2")
    upgraded = LLMStore(store.path)
    assert not upgraded._unavailable
    assert upgraded.count_conversation_messages("g") == 1
    with upgraded._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_loops").fetchone()[0] == 0
        versions = {row[0] for row in conn.execute("SELECT version FROM agent_schema_migrations")}
        assert versions == {1, 2, 3, 4}
    assert (
        LLMStore(store.path).get_or_create_chat_session("g")
        == upgraded.get_or_create_chat_session("g")
    )


def test_unavailable_store_has_no_transient_chat_fallback(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    store._unavailable = True
    with pytest.raises(SessionStoreError):
        store.get_or_create_chat_session("g")


def test_resume_failure_restores_active_and_archive_state(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    original = store.start_private_chat_session("u")
    generation, _ = store.agent_scope_state("private:u")
    store.append_session_reply(
        "private:u", original, generation, user_message=None, assistant_text="archived",
    )
    store.end_private_chat_session("u", save=True, persona_id=None, preset="")
    current = store.start_private_chat_session("u")
    current_generation, _ = store.agent_scope_state("private:u")
    store.append_session_reply(
        "private:u", current, current_generation, user_message=None, assistant_text="current",
    )
    with store._connect() as conn:
        conn.execute(
            "CREATE TRIGGER fail_resume BEFORE DELETE ON session_archives "
            "BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(SessionStoreError):
        store.resume_private_chat_session("u", 1)
    assert store.get_or_create_chat_session("private:u") == (current, current_generation)
    assert store.list_recent_conversation_messages("private:u", 10)[0]["content"] == "current"
    assert store.list_recent_conversation_messages("archive:u:1", 10)[0]["content"] == "archived"
    assert store.get_session_archive("u", 1) is not None


def test_delete_archive_closes_identity_without_touching_current_session(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    original = store.start_private_chat_session("u")
    generation, _ = store.agent_scope_state("private:u")
    store.append_session_reply(
        "private:u", original, generation, user_message=None, assistant_text="archived",
    )
    store.end_private_chat_session("u", save=True, persona_id=None, preset="")
    current = store.start_private_chat_session("u")
    assert store.delete_archived_chat_session("u", 1)
    assert "error" in store.resume_private_chat_session("u", 1)
    assert store.get_chat_session("private:u") == current
    assert store.count_conversation_messages("archive:u:1") == 0
