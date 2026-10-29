"""Synthetic storage stages executed with either the baseline or candidate package."""

import sys
from pathlib import Path


def seed():
    import json
    from pathlib import Path
    from quickquip.llm.config_service import ConfigService
    from quickquip.llm.store import LLMStore
    from quickquip.games.niuniu.store import NiuNiuStore
    from quickquip.chat.scheduled_messages import ScheduledMessageStore
    import quickquip.llm.config_store as module

    root = Path(sys.argv[1])
    assert module.SCHEMA_VERSION == 3
    service = ConfigService(root / "data/llm_config.db", config_dir=root / "config")
    service.initialize()
    document = service.read()["document"]
    document["settings"]["runtime"]["history_limit"] = 37
    service.replace(document, 1, note="synthetic unpublished draft")
    task = service.apply(2, "synthetic-pending-apply")
    store = LLMStore(root / "data/llm.db")
    store.append_conversation_message("12345", "42", "user", "before migration")
    store.update_group_settings("12345", enabled=False, history_limit=0)
    store.update_group_settings("private:67890", enabled=True, history_limit=12)
    game = NiuNiuStore(str(root / "data/niuniu.db"))
    game.register("42")
    game.set_group_text_mode("12345", "default")
    schedules = ScheduledMessageStore(root / "data/scheduled_messages.json")
    repeat = schedules.add(cron="0 8 * * *", group_ids=["12345"], message="repeat")
    once = schedules.add(cron="0 8 * * *", group_ids=["12345"], message="once", recurring=False)
    (root / "data/expected.json").write_text(
        json.dumps({"task": task["id"], "repeat": repeat.id, "once": once.id})
    )
    service.store.verify()
    print(json.dumps({"stage": "seed_v1.16.3", "schema": module.SCHEMA_VERSION}))


def upgrade():
    import json
    from pathlib import Path
    from quickquip.configuration.migration import migrate, require_fresh_layout
    from quickquip.configuration.errors import ConfigError
    from quickquip.llm.config_service import ConfigService
    from quickquip.llm.store import LLMStore
    from quickquip.chat.scheduled_messages import ScheduledMessageStore

    root = Path(sys.argv[1])
    try:
        require_fresh_layout(root)
    except ConfigError as exc:
        assert exc.code == "migration_required"
    else:
        raise AssertionError("old layout was not rejected")
    # A failed extraction restores the original layout before retry.
    from unittest.mock import patch
    from quickquip.configuration import legacy_storage

    try:
        with patch.object(legacy_storage, "text_modes", side_effect=OSError("synthetic failure")):
            migrate(root, services_stopped=True)
    except OSError as error:
        assert str(error) == "synthetic failure"
    else:
        raise AssertionError("injected migration failure was ignored")
    assert (root / "data/llm_config.db").exists()
    assert not (root / "config/managed/config.db").exists()
    result = migrate(root, services_stopped=True)
    assert result["status"] == "complete"
    require_fresh_layout(root)
    expected = json.loads((root / "data/expected.json").read_text())
    service = ConfigService(root / "config/managed/config.db", config_dir=root / "config")
    assert service.read()["revision"] == 2
    assert service.read("published")["revision"] == 1
    assert service.version()["note"] == "synthetic unpublished draft"
    assert service.tasks.get(expected["task"])["status"] == "queued"
    assert service.scope_settings.get_group_settings("12345").history_limit == 0
    assert service.scope_settings.get_group_settings("private:67890").enabled is None
    store = LLMStore(root / "data/llm.db")
    assert store.private_chat_active("67890") is True
    store.append_conversation_message("12345", "42", "user", "after migration")
    store.set_private_chat_active("67890", False)
    service.scope_settings.update_group_settings("12345", history_limit=19)
    document = service.read()["document"]
    document["settings"]["runtime"]["history_limit"] = 41
    service.replace(document, 2, note="changed after migration")
    claim = service.tasks.claim("synthetic-candidate")
    service.tasks.finish(claim["id"], claim["claim_token"])
    schedules = ScheduledMessageStore(
        root / "config/managed/scheduled_messages.json",
        pending_path=root / "data/pending_scheduled_messages.json",
    )
    schedules.remove(expected["once"])
    assert migrate(root, services_stopped=True)["changed"] is False
    (root / "data/migration-result.json").write_text(json.dumps(result))
    print(
        json.dumps(
            {
                "stage": "upgrade_and_new_activity",
                "schema": 4,
                "draft": 3,
                "published": 1,
                "migration_counts": result["migrated"],
            }
        )
    )


def reverse():
    import json
    from pathlib import Path
    from quickquip.configuration.migration import rollback

    root = Path(sys.argv[1])
    result = json.loads((root / "data/migration-result.json").read_text())
    reversed_result = rollback(root, result["backup"], services_stopped=True)
    assert reversed_result["business_data_retained"]
    assert not (root / "config/managed/config.db").exists()
    print(json.dumps({"stage": "reverse_to_schema3", "business_data_retained": True}))


def old_read():
    import json
    import sqlite3
    from pathlib import Path
    from quickquip.llm.config_service import ConfigService
    from quickquip.llm.store import LLMStore
    from quickquip.games.niuniu.store import NiuNiuStore
    from quickquip.chat.scheduled_messages import ScheduledMessageStore
    from quickquip.llm.config_store import SCHEMA_VERSION

    root = Path(sys.argv[1])
    assert SCHEMA_VERSION == 3
    expected = json.loads((root / "data/expected.json").read_text())
    service = ConfigService(root / "data/llm_config.db", config_dir=root / "config")
    service.initialize()
    assert service.read()["revision"] == 3
    assert service.read()["document"]["settings"]["runtime"]["history_limit"] == 41
    assert service.read("published")["revision"] == 1
    assert service.version()["note"] == "changed after migration"
    assert service.tasks.get(expected["task"])["status"] == "succeeded"
    store = LLMStore(root / "data/llm.db")
    assert store.get_group_settings("private:67890").enabled is False
    assert store.get_group_settings("12345").history_limit == 19
    assert len(store.list_recent_conversation_messages("12345", limit=10)) == 2
    game = NiuNiuStore(str(root / "data/niuniu.db"))
    assert game.get_group_text_mode("12345") == "default"
    with sqlite3.connect(root / "data/niuniu.db") as conn:
        assert conn.execute("SELECT count(*) FROM niuniu_users").fetchone()[0] == 1
    schedules = ScheduledMessageStore(root / "data/scheduled_messages.json")
    assert [job.id for job in schedules.list()] == [expected["repeat"]]
    store.append_conversation_message("12345", "42", "user", "old version after rollback")
    print(
        json.dumps(
            {
                "stage": "v1.16.3_read_write_after_rollback",
                "draft": 3,
                "published": 1,
                "messages": 3,
                "consumed_one_off_absent": True,
            }
        )
    )


def reupgrade():
    import json
    from pathlib import Path
    from quickquip.configuration.migration import migrate
    from quickquip.llm.config_service import ConfigService
    from quickquip.llm.store import LLMStore

    root = Path(sys.argv[1])
    result = migrate(root, services_stopped=True)
    assert result["status"] == "complete"
    service = ConfigService(root / "config/managed/config.db", config_dir=root / "config")
    service.store.verify()
    assert service.read()["revision"] == 3
    store = LLMStore(root / "data/llm.db")
    assert len(store.list_recent_conversation_messages("12345", limit=10)) == 3
    assert store.private_chat_active("67890") is False
    print(json.dumps({"stage": "second_upgrade", "messages": 3, "private_active": False}))


def business_seed():
    from quickquip.llm.store import LLMStore
    from quickquip.games.niuniu.store import NiuNiuStore

    root = Path(sys.argv[1]) / "data/business-install"
    root.mkdir()
    store = LLMStore(root / "data/llm.db")
    store.update_group_settings("12345", enabled=False)
    game = NiuNiuStore(str(root / "data/niuniu.db"))
    game.register("42")
    game.set_group_text_mode("12345", "default")
    assert not (root / "data/llm_config.db").exists()


def business_upgrade():
    from quickquip.configuration.migration import migrate
    from quickquip.llm.config_service import ConfigService

    root = Path(sys.argv[1]) / "data/business-install"
    result = migrate(root, services_stopped=True)
    assert result["status"] == "complete"
    service = ConfigService(root / "config/managed/config.db", config_dir=root / "config")
    assert service.scope_settings.get_group_settings("12345").enabled is False
    assert service.read()["document"]["providers"] == []
    print('{"stage":"business_only","result":"passed"}')


if __name__ == "__main__":
    stage = sys.argv.pop(1)
    # Explicit source precedence also works with Windows embedded Python ._pth.
    source = sys.argv.pop(2)
    sys.path.insert(0, str(Path(source).resolve()))
    {
        "business_seed": business_seed,
        "business_upgrade": business_upgrade,
        "seed": seed,
        "upgrade": upgrade,
        "reverse": reverse,
        "old_read": old_read,
        "reupgrade": reupgrade,
    }[stage]()
