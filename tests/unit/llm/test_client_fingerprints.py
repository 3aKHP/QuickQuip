"""Profile ownership, wire behavior, deployment identity and upgrade boundaries."""
from __future__ import annotations

from dataclasses import replace
from importlib import metadata
from importlib.resources import files
import json
import multiprocessing
import sqlite3
import uuid

import httpx
import pytest

from quickquip.llm.client_fingerprints.catalog import (
    FingerprintRuntime, _load_catalog, get_catalog, parse_profile, profile_metadata,
    resolve_profile,
)
from quickquip.llm.client_fingerprints.identity import client_version, load_install_id
from quickquip.llm.config import ProviderConfig
from quickquip.llm.config_document import ConfigError, compile_document, empty_document
from quickquip.llm.config_service import ConfigService
from quickquip.llm import config_store
from quickquip.llm.epoch import create_epoch_id
from quickquip.llm.provider import LLMProviderError, LLMRequest, RetryPolicy, build_provider_client
from quickquip.llm.provider import base
from quickquip.llm.session import create_session_identity
from quickquip.llm.tools import LLMConversationMessage


@pytest.fixture(autouse=True)
def installed_version(monkeypatch):
    original = metadata.version
    monkeypatch.setattr(metadata, "version",
                        lambda name: "2.3.4.dev5" if name == "quickquip" else original(name))
    client_version.cache_clear()
    yield
    client_version.cache_clear()


def _config(tmp_path, protocol="openai", **changes):
    profile = resolve_profile("quickquip", protocol)
    return ProviderConfig(
        id="test", protocol=protocol, base_url="https://example.test/v1",
        api_key_env="FINGERPRINT_TEST_KEY", default_model="m", models=["m"],
        stream_enabled=False, client_fingerprint="quickquip",
        fingerprint_runtime=FingerprintRuntime(profile, "synthetic-cluster", tmp_path),
        **changes,
    )


def _request():
    return LLMRequest(
        model="m", system_prompt="system", messages=[LLMConversationMessage("user", "hi")],
        temperature=0.5, max_output_tokens=32,
        session=create_session_identity(), epoch_id=create_epoch_id(),
    )


def _document():
    doc = empty_document()
    doc["providers"] = [{
        "id": "test", "protocol": "openai", "base_url": "https://example.test/v1",
        "api_key_env": "FINGERPRINT_TEST_KEY", "default_model": "m",
        "models": [{"model": "m"}], "client_fingerprint": "quickquip",
    }]
    doc["settings"]["runtime"]["client_cluster"] = "synthetic-cluster"
    return doc


@pytest.mark.parametrize("protocol,client,ua", [
    ("openai", "opencode2", "opencode/latest/2.0.27/cli"),
    ("openai_responses", "codex",
     "codex-tui/0.162.1 (Ubuntu 24.04; x86_64) unknown (codex-tui; 0.162.1)"),
])
@pytest.mark.parametrize("local_override", [False, True])
async def test_implicit_default_sends_client_identity_and_body(
    tmp_path, monkeypatch, protocol, client, ua, local_override,
):
    directory = tmp_path / "config"
    if local_override:
        overrides = directory / "client_profiles"
        overrides.mkdir(parents=True)
        source = files("quickquip.llm.client_fingerprints").joinpath(f"defaults/{client}.toml")
        (overrides / f"{client}.toml").write_text(source.read_text().replace(ua, "Edited/1"))
        ua = "Edited/1"
    doc = _document()
    provider = doc["providers"][0]
    provider.pop("client_fingerprint")
    provider["protocol"] = protocol
    provider["parameters"] = {"stream_enabled": False}
    cfg = compile_document(doc, config_dir=directory).providers["test"]
    captured = []
    def handler(sent):
        captured.append(sent)
        if protocol == "openai":
            return httpx.Response(200, json={"model": "m", "choices": [
                {"message": {"content": "ok"}, "finish_reason": "stop"},
            ]})
        return httpx.Response(200, json={"model": "m", "status": "completed", "output": [
            {"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": "ok"},
            ]},
        ]})
    original = httpx.AsyncClient
    monkeypatch.setenv("FINGERPRINT_TEST_KEY", "synthetic-key")
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    req = _request()
    response = await build_provider_client(cfg).complete(req)
    assert response.text == "ok" and cfg.client_fingerprint == "default"
    sent = captured[0]
    assert sent.headers["user-agent"] == ua
    assert not any(k.startswith("x-quickquip-") for k in sent.headers)
    body = json.loads(sent.content)
    if protocol == "openai":
        sessions = {sent.headers[k] for k in (
            "x-opencode-session", "x-opencode-session-id", "x-session-affinity", "x-session-id",
        )}
        assert len(sessions) == 1 and next(iter(sessions)).startswith("ses_")
        assert body["max_completion_tokens"] == req.max_output_tokens
        assert "max_tokens" not in body and body["store"] is False
        assert sent.headers["accept-encoding"] == "gzip, deflate, br, zstd"
    else:
        assert body["prompt_cache_key"] == req.session.id
        assert all(sent.headers[k] == req.session.id for k in (
            "session-id", "thread-id", "x-client-request-id",
        ))
        assert sent.headers["originator"] == "codex-tui"
        assert body["instructions"] == req.system_prompt


@pytest.mark.parametrize("protocol", ["openai", "claude", "gemini", "openai_responses"])
async def test_brand_headers_use_epoch_and_leave_body_unchanged(tmp_path, monkeypatch, protocol):
    monkeypatch.setenv("FINGERPRINT_TEST_KEY", "synthetic-key")
    config = _config(tmp_path, protocol)
    request = _request()
    url, headers, body = await build_provider_client(config)._build_request_parts(request)
    default = replace(config, client_fingerprint="default", fingerprint_runtime=FingerprintRuntime(
        resolve_profile("default", protocol), "", tmp_path,
    ))
    default_url, default_headers, default_body = await build_provider_client(
        default,
    )._build_request_parts(request)
    assert (url, body) == (default_url, default_body)
    assert headers["user-agent"] == f"QuickQuip/{metadata.version('quickquip')}"
    assert headers["x-quickquip-client"] == metadata.version("quickquip")
    assert headers["x-quickquip-session"] == request.epoch_id != request.session.id
    assert headers["x-quickquip-install"] == load_install_id(tmp_path)
    assert headers["x-quickquip-cluster"] == "synthetic-cluster"
    assert not any(key.lower().startswith("x-quickquip-") for key in default_headers)
    if protocol == "claude":
        assert not any(key.startswith("x-stainless-") for key in headers)
        assert "x-app" not in headers
        assert "anthropic-dangerous-direct-browser-access" not in headers
        assert "claude-code" not in headers["anthropic-beta"]
        assert headers["anthropic-version"] == default_headers["anthropic-version"]
        assert "interleaved-thinking" in headers["anthropic-beta"]


@pytest.mark.parametrize("protocol", ["openai", "claude", "gemini", "openai_responses"])
async def test_user_agent_overrides_are_case_insensitive(tmp_path, monkeypatch, protocol):
    monkeypatch.setenv("FINGERPRINT_TEST_KEY", "synthetic-key")
    config = _config(tmp_path, protocol, headers={"User-Agent": "relay-client"})
    request = _request()
    _, headers, _ = await build_provider_client(config)._build_request_parts(request)
    assert [(k, v) for k, v in headers.items() if k.lower() == "user-agent"] == [
        ("User-Agent", "relay-client"),
    ]
    _, headers, _ = await build_provider_client(
        replace(config, user_agent="explicit-client"),
    )._build_request_parts(request)
    assert [(k, v) for k, v in headers.items() if k.lower() == "user-agent"] == [
        ("user-agent", "explicit-client"),
    ]
    assert headers["x-quickquip-client"] == client_version()


async def test_absent_cluster_and_epoch_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("FINGERPRINT_TEST_KEY", "synthetic-key")
    config = _config(tmp_path)
    config.fingerprint_runtime = replace(config.fingerprint_runtime, cluster="")
    request = _request()
    _, headers, _ = await build_provider_client(config)._build_request_parts(request)
    assert "x-quickquip-cluster" not in headers
    for epoch_id in (None, "bad", str(uuid.uuid1())):
        with pytest.raises(LLMProviderError, match="missing_epoch_identity"):
            await build_provider_client(config)._build_request_parts(
                replace(request, epoch_id=epoch_id),
            )


@pytest.mark.parametrize("selection", ["default", "quickquip"])
@pytest.mark.parametrize("name", ["X-QuickQuip-Install", "x-quickquip-session",
                                  "X-QUICKQUIP-CLUSTER", "x-quickquip-client"])
async def test_manual_owned_headers_rejected_in_config_and_runtime(
    tmp_path, monkeypatch, selection, name,
):
    monkeypatch.setenv("FINGERPRINT_TEST_KEY", "synthetic-key")
    doc = _document()
    doc["providers"][0].update(client_fingerprint=selection, headers={name: "synthetic"})
    with pytest.raises(ConfigError) as error:
        compile_document(doc, config_dir=tmp_path / "config")
    assert error.value.code == "profile_owned_header"
    config = replace(_config(tmp_path), client_fingerprint=selection,
                     fingerprint_runtime=None, headers={name: "synthetic"})
    with pytest.raises(LLMProviderError, match="profile_owned_header"):
        await build_provider_client(config)._build_request_parts(_request())


def test_local_overrides_and_apply_use_one_file_snapshot(tmp_path):
    directory = tmp_path / "config"
    overrides = directory / "client_profiles"
    overrides.mkdir(parents=True)
    source = files("quickquip.llm.client_fingerprints").joinpath("defaults/quickquip.toml")
    custom = source.read_text(encoding="utf-8").replace("QuickQuip/{client_version}",
                                                     "QuickQuipLocal/{client_version}")
    path = overrides / "quickquip.toml"
    path.write_text(custom, encoding="utf-8")
    service = ConfigService(tmp_path / "data/llm_config.db")
    service.initialize()
    draft = service.replace(_document(), 1)
    config = compile_document(draft["document"], config_dir=directory)
    assert config.providers["test"].fingerprint_runtime.profile.user_agent.startswith(
        "QuickQuipLocal/",
    )
    assert config.providers["test"].fingerprint_runtime.cluster == "synthetic-cluster"
    path.write_text("invalid TOML", encoding="utf-8")
    same = compile_document(draft["document"], config_dir=directory)
    assert (
        same.providers["test"].fingerprint_runtime == config.providers["test"].fingerprint_runtime
    )
    # A fresh process would load the broken override rather than silently use the bundle.
    _load_catalog.cache_clear()
    with pytest.raises(ConfigError, match="Profile"):
        get_catalog(directory)
    path.write_text(custom, encoding="utf-8")
    _load_catalog.cache_clear()


def test_custom_catalog_selection_and_invalid_file_policies(tmp_path):
    directory = tmp_path / "config"
    overrides = directory / "client_profiles"
    overrides.mkdir(parents=True)
    text = 'format_version=1\nid="custom"\nlabel="Custom"\n[protocols.openai]\n'
    (overrides / "custom.toml").write_text(text)
    doc = _document()
    doc["providers"][0]["client_fingerprint"] = "custom"
    effective = compile_document(doc, config_dir=directory).providers["test"]
    assert effective.client_fingerprint == "custom"
    assert "custom" in {entry["id"] for entry in profile_metadata(directory)}
    for bad in (text.replace('id="custom"', 'id="mismatch"'),
                text + '[protocols.openai.bindings]\nx-custom="arbitrary"\n',
                text + '[headers]\nx-quickquip-client="forbidden"\n',
                text + 'unknown_field=true\n'):
        with pytest.raises(ConfigError):
            parse_profile(bad, "custom")


def _identity_worker(directory, queue):
    from pathlib import Path

    queue.put(load_install_id(Path(directory)))


def test_install_identity_is_shared_across_processes_and_never_repairs_corruption(tmp_path):
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    workers = [context.Process(target=_identity_worker, args=(str(tmp_path), queue))
               for _ in range(3)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(20)
        assert worker.exitcode == 0
    identities = {queue.get(timeout=2) for _ in workers}
    assert identities == {load_install_id(tmp_path)}
    path = tmp_path / "client_identity.json"
    original = path.read_bytes()
    assert len(json.loads(original)["install_id"]) == 64
    path.write_text('{"install_id":"damaged"}\n')
    with pytest.raises(ConfigError) as error:
        load_install_id(tmp_path)
    assert error.value.code == "client_identity_failed"
    assert path.read_text() == '{"install_id":"damaged"}\n'


async def test_retry_and_fallback_keep_frozen_brand_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("FINGERPRINT_TEST_KEY", "synthetic-key")
    monkeypatch.setattr(base, "_schedule_usage_record", lambda *args: None)
    seen = []
    statuses = [503, 503, 200]

    def handler(request):
        seen.append(request)
        return httpx.Response(statuses.pop(0), json={"choices": [{"message": {"content": "ok"}}]})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(base.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=transport, **kwargs))
    config = _config(tmp_path, fallback_urls=["https://fallback.test/v1"])
    request = _request()
    client = build_provider_client(config, retry_policy=RetryPolicy(2, 0, 0))
    result = await client.complete(request)
    assert result.text == "ok"
    assert len(seen) == 3
    assert {r.headers["x-quickquip-session"] for r in seen} == {request.epoch_id}
    assert {r.headers["x-quickquip-install"] for r in seen} == {load_install_id(tmp_path)}
    assert {r.url.host for r in seen} == {"example.test", "fallback.test"}


@pytest.mark.parametrize("recorded_boot", [False, True])
def test_v1_database_upgrade_preserves_revisions_and_snapshots(tmp_path, recorded_boot):
    path = tmp_path / "data/llm_config.db"
    path.parent.mkdir()
    doc = empty_document()
    doc["settings"]["runtime"].pop("client_cluster")
    with sqlite3.connect(path) as conn:
        conn.executescript(config_store._SCHEMA + config_store.declared_schema(legacy=True))
        conn.execute("INSERT INTO config_meta VALUES(1,1,4,2,?)", (config_store.dumps(doc),))
        conn.execute("INSERT INTO config_snapshots VALUES(2,?,123)", (config_store.dumps(doc),))
        config_store.project_document(conn, doc)
        if recorded_boot:
            conn.execute("INSERT INTO bot_runtime VALUES(1,'old-boot',2,'old-version',0,'{}')")
    service = ConfigService(path)
    with pytest.raises(ConfigError) as error:
        service.initialize()
    assert error.value.code == "services_running"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT schema_version FROM config_meta").fetchone()[0] == 1
        assert "client_cluster" not in {
            row[1] for row in conn.execute("PRAGMA table_info(runtime_settings)")
        }

    assert service.initialize(services_stopped=True)["revision"] == 4
    assert service.status()["schema_version"] == 2
    assert service.read("published")["document"] == doc
    with service.store.connect() as conn:
        assert conn.execute("SELECT created_at FROM config_snapshots").fetchone()[0] == 123
    replacement = _document()
    assert service.replace(replacement, 4)["revision"] == 5
    effective = compile_document(service.read()["document"])
    assert effective.runtime.client_cluster == "synthetic-cluster"


def test_default_and_explicit_catalog_calls_share_startup_snapshot(tmp_path, monkeypatch):
    from quickquip.llm.client_fingerprints import catalog

    overrides = tmp_path / "client_profiles"
    overrides.mkdir()
    path = overrides / "custom.toml"
    path.write_text('format_version=1\nid="custom"\nlabel="Custom"\n[protocols.openai]\n')
    monkeypatch.setattr(catalog, "CONFIG_DIR", tmp_path)
    initial = get_catalog()
    path.write_text("invalid TOML")
    assert get_catalog(tmp_path) is initial
    assert get_catalog(tmp_path / ".." / tmp_path.name) is initial
    assert "custom" in {entry["id"] for entry in profile_metadata(tmp_path)}


def test_isolated_cli_import_and_schema_do_not_read_unrelated_profiles(tmp_path, monkeypatch):
    from quickquip.llm import config_cli
    from quickquip.llm.client_fingerprints import catalog

    unrelated = tmp_path / "unrelated"
    (unrelated / "client_profiles").mkdir(parents=True)
    (unrelated / "client_profiles/broken.toml").write_text("invalid TOML")
    monkeypatch.setattr(catalog, "CONFIG_DIR", unrelated)
    monkeypatch.setattr("quickquip.common.paths.CONFIG_DIR", unrelated)
    directory = tmp_path / "config/client_profiles"
    directory.mkdir(parents=True)
    (directory / "custom.toml").write_text(
        'format_version=1\nid="custom"\nlabel="Custom"\n[protocols.openai]\n',
    )
    path = tmp_path / "data/llm_config.db"
    ConfigService(path).initialize()
    doc = _document()
    doc["providers"][0]["client_fingerprint"] = "custom"
    exchange = tmp_path / "exchange.json"
    exchange.write_text(json.dumps(doc))
    for command in (["validate", str(exchange)],
                    ["import", str(exchange), "--expected-revision", "1"]):
        result = config_cli.execute(config_cli.parser().parse_args(["--db", str(path), *command]))
        assert result.get("valid", True)
    assert ConfigService(path).read()["document"]["providers"][0]["client_fingerprint"] == "custom"


async def test_uninstalled_source_uses_unknown_version_once(tmp_path, monkeypatch, caplog):
    def unavailable(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", unavailable)
    monkeypatch.setenv("FINGERPRINT_TEST_KEY", "synthetic-key")
    client_version.cache_clear()
    client = build_provider_client(_config(tmp_path))
    for _ in range(2):
        _, headers, _ = await client._build_request_parts(_request())
        assert headers["user-agent"] == "QuickQuip/unknown"
        assert headers["x-quickquip-client"] == "unknown"
    assert sum("package metadata" in record.message for record in caplog.records) == 1
