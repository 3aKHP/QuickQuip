"""Protect strict writes, effective overrides and credential-free JSON migration."""

from copy import deepcopy
import json
from pathlib import Path
import tomllib

import pytest

from quickquip.llm.config_document import (
    ConfigError,
    compile_document,
    effective_parameters,
    empty_document,
    resolve_model_provider,
    upgrade_document,
    validate_document,
)
from quickquip.llm.config_migration import migrate_legacy
from quickquip.llm.config_legacy import load_llm_config
from tests.fixtures.configs import MIN_LLM_CONFIG_TOML


def document():
    doc = empty_document()
    doc["providers"] = [
        {
            "id": "p",
            "protocol": "openai",
            "base_url": "https://example.test/v1",
            "api_key_env": "QQ_TEST_KEY",
            "default_model": "org/model",
            "parameters": {
                "temperature": 0.5,
                "stream_enabled": True,
                "extra_body": {"a": {"b": 1}},
                "style_profile": "shared",
                "style_overrides": "append",
            },
            "models": [
                {
                    "model": "org/model",
                    "parameters": {
                        "temperature": 0,
                        "stream_enabled": False,
                        "extra_body": {},
                        "style_overrides": "",
                    },
                }
            ],
            "aliases": [{"alias": "short", "model": "org/model"}],
        }
    ]
    doc["style_profiles"] = {"shared": "style"}
    doc["routes"]["daily_summary"] = [{"provider_id": "p", "model": "org/model"}, "@default"]
    return validate_document(doc)


def test_zero_false_empty_object_and_style_replace_provider_defaults(tmp_path):
    config = compile_document(document(), tmp_path)
    resolved = resolve_model_provider(config, "p", "short")
    assert resolved.temperature == 0
    assert resolved.stream_enabled is False
    assert resolved.extra_body == {}
    assert resolved.style_overrides == "style"
    assert config.providers["p"].extra_body == {"a": {"b": 1}}
    assert config.daily_summary.model_cascade == ["p/org/model", "@default"]
    # Call parameters take precedence without mutating the snapshot.
    called = resolve_model_provider(
        config, "p", "org/model", {"temperature": 1, "style_profile": ""}
    )
    assert called.temperature == 1 and called.style_overrides == ""
    assert resolved.temperature == 0


def test_null_inherits_and_sources_remain_unexpanded(tmp_path, monkeypatch):
    doc = document()
    doc["providers"][0]["parameters"]["user_agent"] = "${QQ_AGENT}"
    doc["providers"][0]["models"][0]["parameters"].update(temperature=None, extra_body=None)
    monkeypatch.setenv("QQ_AGENT", "private-sentinel")
    config = compile_document(doc, tmp_path)
    assert resolve_model_provider(config, "p", "org/model").user_agent == "private-sentinel"
    effective = effective_parameters(doc, "p", "org/model")
    assert effective["temperature"]["value"] == 0.5
    assert effective["temperature"]["source"] == "provider"
    assert effective["user_agent"]["value"] == "${QQ_AGENT}"
    assert "private-sentinel" not in json.dumps(effective)


@pytest.mark.parametrize(
    "key,value",
    [
        ("temperature", -0.1),
        ("stream_enabled", "false"),
        ("max_output_tokens", 0),
        ("retry_jitter", 2),
        ("agent_replay_loop_tokens", 511),
        ("timeout_seconds", 0),
        ("base_url", "https://other.test"),
        ("extra_body", []),
        ("temperature", float("nan")),
    ],
)
def test_model_writes_reject_invalid_fields_instead_of_clamping(key, value):
    doc = document()
    doc["providers"][0]["models"][0]["parameters"][key] = value
    with pytest.raises(ConfigError):
        validate_document(doc)


def test_epoch_relations_are_validated_across_inheritance():
    doc = document()
    doc["providers"][0]["parameters"]["epoch_hot_target_tokens"] = 70000
    with pytest.raises(ConfigError, match="纪元"):
        validate_document(doc)


@pytest.mark.parametrize("location", ["headers", "extra_body", "url", "mcp"])
def test_literal_credentials_never_persist_or_appear_in_errors(location):
    doc = document()
    sentinel = "sk-private-sentinel-123"
    p = doc["providers"][0]
    if location == "headers":
        p["headers"] = {"Authorization": "Bearer " + sentinel}
    elif location == "extra_body":
        p["parameters"]["extra_body"] = {"nested": {"api_key": sentinel}}
    elif location == "url":
        p["base_url"] = "https://example.test/?token=" + sentinel
    else:
        doc["settings"]["mcp"]["servers"] = [{"id": "secret", "env": {"MY_TOKEN": sentinel}}]
    with pytest.raises(ConfigError) as caught:
        validate_document(doc)
    assert caught.value.code == "literal_secret"
    assert sentinel not in str(caught.value) + json.dumps(caught.value.as_dict())


def test_missing_disabled_route_reference_blocks_save():
    doc = document()
    doc["routes"]["monthly_report"] = [{"provider_id": "gone", "model": "x"}]
    with pytest.raises(ConfigError) as caught:
        validate_document(doc)
    assert caught.value.code == "dependency_conflict"
    assert caught.value.field_path == "routes.monthly_report[0]"


@pytest.mark.parametrize("location", ["base_url", "fallback_urls", "mcp"])
@pytest.mark.parametrize(
    "url",
    [
        "HTTPS://synthetic-user:private-url-sentinel@example.test/v1",
        "hTtPs://example.test/v1?api_key=private-url-sentinel",
        " \tHTTPS://example.test/v1?token=private-url-sentinel",
        "ht\ttps://example.test/v1?token=private-url-sentinel",
    ],
)
def test_parsed_authentication_urls_cannot_enter_database(tmp_path, location, url):
    from quickquip.llm.config_service import ConfigService

    service = ConfigService(tmp_path / "config.db")
    service.initialize()
    before = service.read()
    doc = document()
    if location == "mcp":
        doc["settings"]["mcp"]["servers"] = [{"id": "remote", "transport": "http", "url": url}]
    else:
        doc["providers"][0][location] = [url] if location == "fallback_urls" else url
    with pytest.raises(ConfigError) as caught:
        service.replace(doc, before["revision"])
    assert caught.value.code == "literal_secret"
    assert "private-url-sentinel" not in json.dumps(caught.value.as_dict())
    assert service.read() == before
    assert service.read("published") == before


def test_parsed_url_references_remain_exportable_and_invalid_urls_have_flat_errors():
    doc = document()
    doc["providers"][0]["base_url"] = " HTTPS://example.test/v1?api_key=${QQ_TEST_KEY}"
    assert validate_document(doc)["providers"][0]["base_url"] == doc["providers"][0]["base_url"]
    doc["providers"][0]["base_url"] = "HTTPS://[invalid]/private-url-sentinel"
    with pytest.raises(ConfigError) as caught:
        validate_document(doc)
    assert caught.value.field_path == "providers[0].base_url"
    assert "private-url-sentinel" not in json.dumps(caught.value.as_dict())


def test_json_roundtrip_preserves_slash_models_and_order():
    doc = document()
    doc["providers"][0]["models"].append({"model": "other/a"})
    normalized = validate_document(doc)
    assert validate_document(json.loads(json.dumps(normalized))) == normalized
    assert [m["model"] for m in normalized["providers"][0]["models"]] == ["org/model", "other/a"]


def test_empty_database_config_compiles_with_llm_disabled(tmp_path):
    config = compile_document(empty_document(), tmp_path)
    assert not config.is_available
    assert config.load_error is None


def test_legacy_migration_keeps_references_prices_and_persona_shared_semantics(
    tmp_path, monkeypatch
):
    source = tmp_path / "config" / "llm.toml"
    source.parent.mkdir()
    source.write_text(
        MIN_LLM_CONFIG_TOML
        + """
[pricing.models."openai-main/gpt-test"]
input_per_mtok = 0.0
output_per_mtok = 0.0
[pricing.models."response-only"]
input_per_mtok = 2.0
output_per_mtok = 3.0
"""
    )
    # Frozen input must preserve references even when local environment contains expanded secrets.
    original = source.read_text().replace(
        "timeout_seconds = 30",
        'headers = { Authorization = "Bearer ${QQ_TEST_KEY}" }\ntimeout_seconds = 30',
    )
    source.write_text(original)
    directory = source.parent / "personas"
    directory.mkdir()
    (directory / "_shared.toml").write_text('shared_system_prompt = "shared"\n')
    monkeypatch.setenv("QQ_TEST_KEY", "private-sentinel")
    frozen = load_llm_config(source, preserve_env=True)
    doc, report = migrate_legacy(source)
    config = compile_document(doc, source.parent)
    assert config.personas["default"].system_prompt == frozen.personas["default"].system_prompt
    assert config.personas["default"].system_prompt == "你是测试人格。"
    assert doc["providers"][0]["headers"]["Authorization"] == "Bearer ${QQ_TEST_KEY}"
    assert "private-sentinel" not in json.dumps(doc) + json.dumps(report)
    assert list(frozen.pricing) == ["openai-main/gpt-test", "response-only"]
    assert list(config.pricing_references) == [("openai-main", "gpt-test")]
    assert config.pricing_references[("openai-main", "gpt-test")].input_per_mtok == 0
    dropped = [c for c in report["changes"] if c["field_path"] == "pricing.response-only"]
    assert dropped[0]["kind"] == "unmatched_dropped"
    assert source.read_text() == original
    assert migrate_legacy(source)[0] == doc
    assert (Path(report["backup"]) / "llm.toml").read_text() == original


def test_migration_reports_limits_and_delivery_mapping(tmp_path):
    source = tmp_path / "llm.toml"
    text = MIN_LLM_CONFIG_TOML.replace("tool_max_rounds = 2", "tool_max_rounds = 64")
    text = text.replace("search_max_calls_per_round = 3", "search_max_calls_per_round = 64")
    text = text.replace(
        "enabled = true\n    default_provider", "enabled = true\n    default_provider"
    )
    text = text.replace("[runtime]\n", "[runtime]\nagent_delivery_enabled = true\n", 1)
    source.write_text(text)
    doc, report = migrate_legacy(source)
    assert doc["settings"]["runtime"]["tool_max_rounds"] == 16
    assert doc["settings"]["auto_search"]["search_max_calls_per_round"] == 32
    assert doc["settings"]["runtime"]["agent_delivery_final_enabled"] is True
    assert doc["settings"]["tools"]["enabled_mode"] == "append"
    assert any(c["kind"] == "mapped_to_delivery_domains" for c in report["changes"])


def test_independent_generation_wins_and_original_multimodal_can_be_extracted(tmp_path):
    source = tmp_path / "llm.toml"
    source.write_text(MIN_LLM_CONFIG_TOML + "\n[image_generation]\nenabled = false\n")
    doc, report = migrate_legacy(source)
    asset = tmp_path / "generation.toml"
    assert tomllib.loads(asset.read_text())["generation"]["image"]["enabled"] is False
    original_asset = "[image]\nenabled = false\n"
    asset.write_text(original_asset)
    _, report = migrate_legacy(source)
    assert asset.read_text() == original_asset
    assert any(w["code"] == "independent_generation_authoritative" for w in report["warnings"])


def test_public_legacy_example_migrates_without_secrets_or_lost_prices(tmp_path):
    example = Path("config/llm.toml.example")
    source = tmp_path / "llm.toml"
    source.write_bytes(example.read_bytes())
    raw = tomllib.loads(example.read_text())
    doc, _ = migrate_legacy(source)
    assert len(doc["providers"]) == len(raw["providers"])
    assert len(doc["pricing"]) == len(raw.get("pricing", {}).get("models", {}))
    assert validate_document(deepcopy(doc)) == doc


def test_format_1_catch_all_prices_upgrade_to_single_provider_owners(tmp_path):
    doc = document()
    doc["providers"].append({**deepcopy(doc["providers"][0]), "id": "q", "aliases": []})
    doc["providers"][1]["models"].append({"model": "only-q"})
    doc["format_version"] = 1
    rate = {"input_per_mtok": 1.0}
    doc["pricing"] = [
        {"provider_id": "p", "model": "org/model", **rate},
        {"provider_id": None, "model": "p/org/model", **rate},  # duplicate of exact row
        {"provider_id": None, "model": "q/org/model", "input_per_mtok": 2.0},  # qualified
        {"provider_id": None, "model": "org/model", **rate},  # both owners already priced
        {"provider_id": None, "model": "only-q", **rate},
        {"provider_id": None, "model": "nobody", **rate},
        {"provider_id": "ghost", "model": "m", **rate},
    ]
    upgraded, changes = upgrade_document(doc)
    assert upgraded["format_version"] == 2
    kinds = [(c["kind"], c.get("provider_id")) for c in changes]
    assert kinds == [
        ("duplicate_dropped", "p"),
        ("converted", "q"),
        ("superseded_dropped", None),
        ("converted", "q"),
        ("unmatched_dropped", None),
        ("unknown_provider_dropped", "ghost"),
    ]
    assert [(r["provider_id"], r["model"], r["input_per_mtok"]) for r in upgraded["pricing"]] == [
        ("p", "org/model", 1.0),
        ("q", "org/model", 2.0),
        ("q", "only-q", 1.0),
    ]
    config = compile_document(doc, tmp_path)
    assert set(config.pricing_references) == {("p", "org/model"), ("q", "org/model"),
                                              ("q", "only-q")}
    assert upgrade_document(upgraded) == (upgraded, [])


def test_bare_catch_all_with_several_unpriced_owners_is_dropped_as_ambiguous():
    doc = document()
    doc["providers"].append({**deepcopy(doc["providers"][0]), "id": "q", "aliases": []})
    doc["format_version"] = 1
    doc["pricing"] = [{"provider_id": None, "model": "org/model", "input_per_mtok": 1.0}]
    upgraded, changes = upgrade_document(doc)
    assert upgraded["pricing"] == []
    assert changes[0]["kind"] == "ambiguous_dropped"
    assert changes[0]["candidates"] == ["p", "q"]


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_non_integer_format_version_is_not_upgraded(version):
    doc = document()
    doc["format_version"] = version
    assert upgrade_document(doc) == (doc, [])
    with pytest.raises(ConfigError) as caught:
        validate_document(doc)
    assert caught.value.code == "unsupported_format"


def test_qualified_catch_all_also_keeps_literal_model_owner_price():
    doc = document()
    for ident, model in (("anthropic", "claude-x"), ("openrouter", "anthropic/claude-x")):
        doc["providers"].append({**deepcopy(doc["providers"][0]), "id": ident, "aliases": [],
                                 "default_model": model, "models": [{"model": model}]})
    doc["format_version"] = 1
    doc["pricing"] = [{"provider_id": None, "model": "anthropic/claude-x", "input_per_mtok": 3.0}]
    upgraded, changes = upgrade_document(doc)
    assert {(r["provider_id"], r["model"]) for r in upgraded["pricing"]} == {
        ("anthropic", "claude-x"), ("openrouter", "anthropic/claude-x")
    }
    assert [c["kind"] for c in changes] == ["converted", "converted"]


@pytest.mark.parametrize("path", ["pricing", "models"])
def test_malformed_format_1_values_are_rejected_not_crashed(path):
    doc = document()
    doc["format_version"] = 1
    doc["pricing"] = [{"provider_id": None, "model": "org/model"}]
    if path == "pricing":
        doc["pricing"][0]["provider_id"] = ["x"]
    else:
        doc["providers"][0]["models"][0]["model"] = ["a"]
    with pytest.raises(ConfigError):
        validate_document(doc)


def test_format_2_requires_existing_price_owner():
    doc = document()
    doc["pricing"] = [{"provider_id": None, "model": "org/model"}]
    with pytest.raises(ConfigError) as caught:
        validate_document(doc)
    assert caught.value.field_path == "pricing[0].provider_id"
    doc["pricing"] = [{"provider_id": "ghost", "model": "org/model"}]
    with pytest.raises(ConfigError) as caught:
        validate_document(doc)
    assert caught.value.code == "dependency_conflict"


def test_cli_and_web_share_missing_price_warning_and_preview_impacts(tmp_path):
    from quickquip.llm.config_service import ConfigService
    from quickquip.llm.config_cli import execute, parser

    service = ConfigService(tmp_path / "llm_config.db")
    service.initialize()
    file = tmp_path / "import.json"
    file.write_text(json.dumps(document()))
    args = parser().parse_args(
        ["--db", str(service.path), "import", str(file), "--expected-revision", "1", "--preview"]
    )
    preview = execute(args)
    assert preview == service.preview_import(document(), 1)
    assert preview["warnings"][0]["code"] == "price_missing"
    assert preview["dependencies"]
    assert preview["components"]["mcp_reconnect"] is False
    assert service.read()["revision"] == 1


def test_url_auth_reference_cannot_hide_literal_credential_parts():
    doc = document()
    doc["providers"][0]["base_url"] = "https://example.test/?api_key=sentinel${TOKEN}"
    with pytest.raises(ConfigError) as caught:
        validate_document(doc)
    assert caught.value.code == "literal_secret"
    assert "sentinel" not in json.dumps(caught.value.as_dict())


def test_legacy_qualified_price_migrates_to_one_provider_price(tmp_path):
    from quickquip.llm.pricing import match_pricing

    source = tmp_path / "llm.toml"
    source.write_text(
        MIN_LLM_CONFIG_TOML
        + """
[pricing.models."openai-main/gpt-test"]
input_per_mtok = 2
output_per_mtok = 3
"""
    )
    doc, report = migrate_legacy(source)
    compiled = compile_document(doc, tmp_path)
    assert match_pricing("openai-main", "gpt-test", compiled.pricing_references).input_per_mtok == 2
    assert match_pricing("other", "openai-main/gpt-test", compiled.pricing_references) is None
    assert report["source_counts"]["pricing"] == 1
    assert len(doc["pricing"]) == 1


def test_interrupted_independent_asset_backup_resumes_and_preserves_all_originals(
    tmp_path, monkeypatch
):
    import quickquip.llm.config_migration as migration

    source = tmp_path / "llm.toml"
    source.write_text(MIN_LLM_CONFIG_TOML)
    personas = tmp_path / "personas"
    personas.mkdir()
    (personas / "a.toml").write_text('id="a"\nsystem_prompt="original-a"\n')
    (personas / "b.toml").write_text('id="b"\nsystem_prompt="original-b"\n')
    real_write = migration.durable_write

    def interrupted(path, content):
        if path.name == "b.toml":
            raise OSError("simulated interruption")
        real_write(path, content)

    monkeypatch.setattr(migration, "durable_write", interrupted)
    with pytest.raises(OSError):
        migrate_legacy(source)
    assert sorted(p.name for p in personas.iterdir()) == ["a.toml", "b.toml"]
    monkeypatch.setattr(migration, "durable_write", real_write)
    _, report = migrate_legacy(source)
    backup = Path(report["backup"]) / "personas"
    assert (backup / "a.toml").read_bytes() == (personas / "a.toml").read_bytes()
    assert (backup / "b.toml").read_bytes() == (personas / "b.toml").read_bytes()
    assert (backup.parent / "assets-backup-complete.json").exists()


def test_interrupted_extraction_does_not_publish_partial_persona(tmp_path, monkeypatch):
    import quickquip.llm.config_migration as migration

    source = tmp_path / "llm.toml"
    source.write_text(MIN_LLM_CONFIG_TOML)
    real_link = migration.os.link

    def interrupted(*args):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(migration.os, "link", interrupted)
    with pytest.raises(OSError):
        migrate_legacy(source)
    assert list((tmp_path / "personas").glob("*.toml")) == []
    monkeypatch.setattr(migration.os, "link", real_link)
    _, report = migrate_legacy(source)
    assert report["assets"][0]["status"] == "ready"
    assert (
        tomllib.loads(next((tmp_path / "personas").glob("*.toml")).read_text())["id"] == "default"
    )


def test_non_initializing_cli_commands_cannot_suppress_legacy_migration(tmp_path):
    from quickquip.llm.config_cli import execute, parser

    legacy = tmp_path / "llm.toml"
    legacy.write_text(MIN_LLM_CONFIG_TOML)
    db = tmp_path / "llm_config.db"
    args = parser().parse_args(["--db", str(db), "status"])
    with pytest.raises(ConfigError) as caught:
        execute(args)
    assert caught.value.code == "not_initialized"
    assert not db.exists()


def test_migration_preserves_frozen_style_whitespace_semantics(tmp_path):
    source = tmp_path / "llm.toml"
    body = MIN_LLM_CONFIG_TOML.replace(
        "timeout_seconds = 30",
        'style_profile = " family "\nstyle_overrides = "  append  "\ntimeout_seconds = 30',
    )
    body += '\n[style_profiles]\nfamily = "  shared  "\n'
    source.write_text(body)
    old = load_llm_config(source, preserve_env=True)
    doc, _ = migrate_legacy(source)
    compiled = compile_document(doc, tmp_path)
    assert compiled.providers["openai-main"].style_overrides == "shared\nappend"
    assert (
        compiled.providers["openai-main"].style_overrides
        == old.providers["openai-main"].style_overrides
    )


def test_existing_business_provider_style_survives_effective_model_resolution():
    from quickquip.llm.config import LLMConfig, ProviderConfig

    provider = ProviderConfig(
        "p", "openai", "https://example.test", "KEY", "m", ["m"], style_overrides="existing-style"
    )
    config = LLMConfig(providers={"p": provider})
    assert resolve_model_provider(config, "p", "m").style_overrides == "existing-style"
    provider.model_parameters = {"m": {"style_overrides": ""}}
    assert resolve_model_provider(config, "p", "m").style_overrides == ""
