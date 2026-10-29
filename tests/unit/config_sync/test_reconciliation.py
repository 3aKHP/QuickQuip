"""A one-way operation acknowledges shared fields without consuming reverse changes."""

from copy import deepcopy

from quickquip.config_sync.reconciliation import acknowledge, plan
from quickquip.configuration.inventory import body, entry
from quickquip.configuration.text import parse


def snapshot():
    return {
        "document": {"providers": [], "settings": {"history": 10, "memory": 20}},
        "scopes": {},
        "text_modes": {},
        "files": {".env": entry(b"# credentials\nKEY=original\nPORT=1234\n")},
    }


def test_push_then_pull_preserves_receiver_edits_and_does_not_mutate_source():
    base = snapshot()
    source, target = deepcopy(base), deepcopy(base)
    source["document"]["settings"]["history"] = 15
    target["document"]["settings"]["memory"] = 30
    source["files"][".env"] = entry(b"# credentials\nKEY=new-secret\nPORT=1234\n")
    target["files"][".env"] = entry(b"# credentials\nKEY=original\nPORT=2345\n")
    saved_source = deepcopy(source)
    push = plan(base, source, target)
    assert not push["conflicts"]
    assert push["target"]["document"]["settings"] == {"history": 15, "memory": 30}
    assert parse(".env", body(push["target"]["files"][".env"])) == {
        "KEY": ["new-secret"],
        "PORT": ["2345"],
    }
    shared = acknowledge(base, source, push["target"])
    assert shared["document"]["settings"] == {"history": 15, "memory": 20}
    assert parse(".env", body(shared["files"][".env"])) == {
        "KEY": ["new-secret"],
        "PORT": ["1234"],
    }
    repeated = plan(shared, source, push["target"])
    assert not repeated["write_changes"]
    assert repeated["target_changes"]
    pull = plan(shared, push["target"], source)
    assert not pull["conflicts"]
    assert pull["target"] == push["target"]
    assert source == saved_source
    assert "new-secret" not in repr({key: value for key, value in push.items() if key != "target"})


def test_conflict_preference_only_resolves_collisions_and_keeps_reverse_change_pending():
    base = snapshot()
    source, target = deepcopy(base), deepcopy(base)
    source["document"]["settings"]["history"] = 15
    target["document"]["settings"].update(history=25, memory=30)
    assert plan(base, source, target)["conflicts"]
    preferred = plan(base, source, target, prefer="source")
    assert preferred["target"]["document"]["settings"] == {"history": 15, "memory": 30}
    retained = plan(base, source, target, prefer="target")
    shared = acknowledge(base, source, retained["target"])
    assert shared["document"]["settings"] == base["document"]["settings"]
    assert plan(shared, source, retained["target"])["conflicts"]
    assert plan(base, source, target, overwrite=True)["target"] == source
    assert plan(None, source, target)["target"] == source


def test_provider_collection_acknowledges_shared_additions_but_keeps_target_removal_pending():
    base = snapshot()
    base["document"]["providers"] = [{"id": "old", "models": [{"model": "one"}]}]
    source, target = deepcopy(base), deepcopy(base)
    source["document"]["providers"].append({"id": "new", "models": [{"model": "two"}]})
    target["document"]["providers"] = []
    push = plan(base, source, target)
    assert not push["conflicts"]
    assert push["target"]["document"]["providers"] == source["document"]["providers"][1:]
    shared = acknowledge(base, source, push["target"])
    assert shared["document"]["providers"] == source["document"]["providers"]
    assert plan(shared, push["target"], source)["target"] == push["target"]
