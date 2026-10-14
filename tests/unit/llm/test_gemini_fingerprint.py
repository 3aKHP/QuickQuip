"""Gemini CLI wire layout, installation identity and continuing session model anchors."""
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from importlib.resources import files
import json
import multiprocessing
from threading import Barrier
from uuid import UUID, uuid4

import httpx
from httpx import AsyncClient as HTTPXClient
import pytest

from quickquip.llm.client_fingerprints.catalog import FingerprintRuntime, resolve_profile
from quickquip.llm.client_fingerprints.identity import load_claude_device_id, load_gemini_install_id
from quickquip.llm.config import ProviderConfig
from quickquip.llm.config_document import ConfigError, compile_document, empty_document
from quickquip.llm.config_service import ConfigService
from quickquip.llm.epoch import create_epoch_id
from quickquip.llm.provider import LLMRequest, build_provider_client
from quickquip.llm.provider import base
from quickquip.llm.session import SessionInvalidated, create_session_identity
from quickquip.llm.store import LLMStore
from quickquip.llm.tools import LLMConversationMessage, LLMToolSpec


def config(tmp_path, profile="gemini-cli", **changes):
    values = dict(id="p", protocol="gemini", base_url="https://example.test/v1beta",
                  api_key_env="GEMINI_PROFILE_KEY", default_model="gemini-a",
                  models=["gemini-a", "gemini-b"], stream_enabled=False,
                  client_fingerprint=profile,
                  fingerprint_runtime=FingerprintRuntime(resolve_profile(profile, "gemini"),
                                                         "", tmp_path))
    values.update(changes)
    return ProviderConfig(**values)


def request(**changes):
    values = dict(model="gemini-a", system_prompt="人格与业务指令", temperature=0.3,
                  max_output_tokens=99, session=create_session_identity(),
                  epoch_id=create_epoch_id(), messages=[LLMConversationMessage("user", "中文")])
    values.update(changes)
    return LLMRequest(**values)


@pytest.fixture
def capture(monkeypatch):
    monkeypatch.setenv("GEMINI_PROFILE_KEY", "synthetic-secret")
    monkeypatch.setattr(base, "_schedule_usage_record", lambda *args: None)
    seen = []

    def handler(req):
        seen.append(req)
        result = {"candidates": [{"content": {"parts": [{"text": "成功"}]},
                                  "finishReason": "STOP"}],
                  "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2}}
        if ":streamGenerateContent" in req.url.path:
            return httpx.Response(200, text="data: " + json.dumps(result) + "\n\n")
        return httpx.Response(200, json=result)

    monkeypatch.setattr(base.httpx, "AsyncClient", lambda **kw: HTTPXClient(
        transport=httpx.MockTransport(handler), **kw,
    ))
    return seen


@pytest.mark.parametrize("profile", ["default", "gemini-cli"])
@pytest.mark.parametrize("stream", [False, True])
async def test_dispatch_preserves_business_and_native_evidence(tmp_path, capture, profile, stream):
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"value": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}
    native = [{"thoughtSignature": "synthetic-signature",
               "functionCall": {"name": "lookup", "args": {"value": "中文"}, "id": "call-1"}}]
    req = request(tools=[LLMToolSpec("lookup", "description", schema)], allow_tool_calls=True,
                  messages=[LLMConversationMessage("user", "中文"),
                            LLMConversationMessage("assistant", "", native_content=native),
                            LLMConversationMessage("tool", "结果", tool_name="lookup",
                                                   tool_call_id="call-1")])
    original = deepcopy(req)
    assert (await build_provider_client(config(tmp_path, profile, stream_enabled=stream))
            .complete(req)).text == "成功"
    sent = capture[0]
    assert sent.headers["user-agent"] == "GeminiCLI-tui/0.64.0/gemini-a (linux; x64; terminal)"
    assert sent.headers["x-goog-api-client"] == "google-genai-sdk/1.30.0 gl-node/v24.18.0"
    assert sent.headers["x-goog-api-key"] == "synthetic-secret"
    assert "synthetic-secret" not in str(sent.url)
    assert dict(sent.url.params) == ({"alt": "sse"} if stream else {})
    assert sent.headers["accept"] == "*/*"
    assert sent.headers["accept-encoding"] == "br, gzip, deflate"
    assert UUID(sent.headers["x-gemini-api-privileged-user-id"]).version == 4
    assert not any(k.startswith("x-quickquip-") for k in sent.headers)
    names = [k.lower() for k, _ in sent.headers.multi_items()]
    assert (names.index("user-agent") < names.index("x-goog-api-client")
            < names.index("content-type"))
    body = json.loads(sent.content)
    assert list(body) == ["contents", "systemInstruction", "tools", "generationConfig"]
    assert sent.content == json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    assert body["systemInstruction"] == {"parts": [{"text": req.system_prompt}], "role": "user"}
    assert list(body["contents"][0]) == ["parts", "role"]
    declaration = body["tools"][0]["functionDeclarations"][0]
    assert list(declaration) == ["name", "description", "parametersJsonSchema"]
    assert declaration["parametersJsonSchema"] == schema
    call = body["contents"][1]["parts"][0]
    assert list(call) == ["functionCall", "thoughtSignature"]
    assert call["functionCall"] == native[0]["functionCall"]
    assert list(call["functionCall"]) == ["id", "args", "name"]
    assert call["thoughtSignature"] == "synthetic-signature"
    assert body["contents"][2]["parts"][0]["functionResponse"]["id"] == "call-1"
    assert body["generationConfig"] == {"temperature": 0.3, "maxOutputTokens": 99}
    assert req == original and req.messages[1].native_content == native


async def test_session_anchor_survives_model_channel_epoch_and_request_copy(tmp_path, capture):
    req = request()
    await build_provider_client(config(tmp_path, "default")).complete(req)
    other = replace(req, model="gemini-b", epoch_id=create_epoch_id())
    await build_provider_client(config(tmp_path, "gemini-cli", id="other")).complete(
        deepcopy(other),
    )
    await build_provider_client(config(tmp_path)).complete(request(model="gemini-b"))
    assert [r.headers["user-agent"].split("/")[2].split(" ")[0] for r in capture] == [
        "gemini-a", "gemini-a", "gemini-b",
    ]
    assert "/gemini-b:" in capture[1].url.path


def test_chat_anchor_migration_restart_archive_clear_and_late_request(tmp_path):
    store = LLMStore(tmp_path / "llm.db")
    original = store.start_private_chat_session("u")
    store.append_conversation_message("private:u", "u", "user", "retained")
    with store._connect() as conn:
        conn.execute("DROP TABLE session_client_models")
        conn.execute("DELETE FROM agent_schema_migrations WHERE version=4")
    store = LLMStore(store.path)
    session = store.get_chat_session("private:u")
    assert session == original and not store._unavailable
    assert session.model_projection.get_or_bind_model("gemini-cli", "a") == "a"
    restarted = LLMStore(store.path)
    assert restarted.get_chat_session("private:u").model_projection.get_or_bind_model(
        "gemini-cli", "b",
    ) == "a"
    archive = restarted.end_private_chat_session("u", save=True, persona_id=None, preset="")
    with pytest.raises(SessionInvalidated):
        session.model_projection.get_or_bind_model("gemini-cli", "late")
    restarted.resume_private_chat_session("u", archive["archive_number"])
    resumed = restarted.get_chat_session("private:u")
    assert resumed.model_projection.get_or_bind_model("gemini-cli", "c") == "a"
    restarted.clear_chat_session("private:u")
    with pytest.raises(SessionInvalidated):
        resumed.model_projection.get_or_bind_model("gemini-cli", "late")
    fresh, _ = restarted.get_or_create_chat_session("private:u")
    assert fresh.model_projection.get_or_bind_model("gemini-cli", "b") == "b"
    with restarted._connect() as conn:
        assert [tuple(r) for r in conn.execute(
            "SELECT session_id, model FROM session_client_models",
        )] == [
            (fresh.id, "b"),
        ]


def test_concurrent_first_model_uses_one_committed_anchor(tmp_path):
    stores = [LLMStore(tmp_path / "llm.db") for _ in range(2)]
    sessions = [s.get_or_create_chat_session("g")[0] for s in stores]
    barrier = Barrier(2)

    def bind(pair):
        i, session = pair
        barrier.wait(timeout=5)
        return session.model_projection.get_or_bind_model("gemini-cli", str(i))

    with ThreadPoolExecutor(max_workers=2) as executor:
        models = list(executor.map(bind, enumerate(sessions)))
    assert models[0] == models[1] and models[0] in ("0", "1")
    assert LLMStore(stores[0].path).get_chat_session("g").model_projection.get_or_bind_model(
        "gemini-cli", "other",
    ) == models[0]


def test_install_override_preserves_automatic_and_other_identities(tmp_path):
    cc = load_claude_device_id(tmp_path)
    automatic = load_gemini_install_id(tmp_path)
    before = json.loads((tmp_path / "client_identity.json").read_text())
    assert UUID(automatic).version == 4
    override = str(uuid4())
    assert load_gemini_install_id(tmp_path, override.upper()) == override
    assert json.loads((tmp_path / "client_identity.json").read_text()) == before
    assert load_gemini_install_id(tmp_path, "") == automatic
    assert load_claude_device_id(tmp_path) == cc
    (tmp_path / "client_identity.json").write_text(
        json.dumps({**before, "gemini_cli_install_id": "bad"}),
    )
    with pytest.raises(ConfigError, match="persistent Gemini"):
        load_gemini_install_id(tmp_path)


def _load_install_in_process(directory):
    return load_gemini_install_id(directory)


def test_independent_processes_share_one_automatic_installation(tmp_path):
    with ProcessPoolExecutor(max_workers=2,
                             mp_context=multiprocessing.get_context("spawn")) as executor:
        identities = list(executor.map(_load_install_in_process, [tmp_path, tmp_path]))
    assert identities[0] == identities[1]
    assert UUID(identities[0]).version == 4
    assert load_gemini_install_id(tmp_path) == identities[0]


def test_deleting_last_archive_removes_its_model_anchor(tmp_path):
    store = LLMStore(tmp_path / "llm.db")
    session = store.start_private_chat_session("u")
    session.model_projection.get_or_bind_model("gemini-cli", "a")
    store.append_conversation_message("private:u", "u", "user", "saved")
    number = store.end_private_chat_session("u", save=True, persona_id=None,
                                            preset="")["archive_number"]
    with store._connect() as conn:
        assert conn.execute("SELECT model FROM session_client_models").fetchone()[0] == "a"
    assert store.delete_archived_chat_session("u", number)
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM session_client_models").fetchone()[0] == 0


@pytest.mark.parametrize("profile,auth", [("gemini-cli", "bearer"), ("legacy-gemini", "api_key")])
async def test_bearer_and_legacy_authentication_remain_explicit(tmp_path, capture, profile, auth):
    await build_provider_client(config(tmp_path, profile, auth_method=auth)).complete(request())
    sent = capture[0]
    assert "x-goog-api-key" not in sent.headers
    if auth == "bearer":
        assert sent.headers["authorization"] == "Bearer synthetic-secret"
        assert not sent.url.query
    else:
        assert sent.url.params["key"] == "synthetic-secret"
        assert "x-gemini-api-privileged-user-id" not in sent.headers
        assert "role" not in json.loads(sent.content)["systemInstruction"]


def test_configuration_override_is_document_only_and_structural_conflicts_are_rejected(tmp_path):
    service = ConfigService(tmp_path / "data/llm_config.db")
    service.initialize()
    doc = empty_document()
    override = str(uuid4())
    doc["settings"]["runtime"]["gemini_cli_install_id"] = override.upper()
    doc["providers"] = [{"id": "p", "protocol": "gemini", "base_url": "https://example.test/v1beta",
                         "api_key_env": "GEMINI_PROFILE_KEY", "default_model": "m",
                         "models": [{"model": "m"}]}]
    cfg = compile_document(doc, config_dir=tmp_path / "config")
    assert cfg.providers["p"].fingerprint_runtime.gemini_cli_install_id == override
    from quickquip.llm.config_document import validate_document
    normalized = validate_document(doc)
    service.replace(normalized, 1)
    with service.store.connect() as conn:
        assert conn.execute("SELECT schema_version FROM config_meta").fetchone()[0] == 2
    reloaded = ConfigService(service.path).read()["document"]
    assert reloaded["settings"]["runtime"]["gemini_cli_install_id"] == override
    for provider_or_model in (doc["providers"][0], doc["providers"][0]["models"][0]):
        provider_or_model["parameters"] = {"extra_body": {"contents": []}}
        with pytest.raises(ConfigError) as error:
            validate_document(doc)
        assert error.value.code == "profile_owned_body"
        provider_or_model.pop("parameters")


async def test_local_template_override_and_ua_override_preserve_precedence(tmp_path, capture):
    directory = tmp_path / "config/client_profiles"
    directory.mkdir(parents=True)
    source = files("quickquip.llm.client_fingerprints").joinpath("defaults/gemini-cli.toml")
    (directory / "gemini-cli.toml").write_text(source.read_text().replace("0.64.0", "9.0.0"))
    profile = resolve_profile("default", "gemini", directory.parent)
    cfg = config(tmp_path, "default", fingerprint_runtime=FingerprintRuntime(profile, "", tmp_path))
    req = request()
    await build_provider_client(cfg).complete(req)
    await build_provider_client(replace(cfg, headers={"User-Agent": "Header/1"})).complete(req)
    await build_provider_client(replace(cfg, headers={"User-Agent": "Header/1"},
                                        user_agent="Explicit/1")).complete(req)
    assert [r.headers["user-agent"] for r in capture] == [
        "GeminiCLI-tui/9.0.0/gemini-a (linux; x64; terminal)", "Header/1", "Explicit/1",
    ]
