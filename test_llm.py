import asyncio
import json
import os
import textwrap
from pathlib import Path
import shutil

import quickquip.llm.service as llm_runtime_module
import plugins.web_search as web_search_module
from plugins.llm_config import MCPServerConfig, ProviderConfig
from plugins.llm_identity import IdentityIndex
from plugins.llm_inputs import extract_llm_input, extract_llm_prompt, extract_private_llm_input
from plugins.llm_mcp import MCPServerStatus, MCPToolBinding, StdioMCPClient
from plugins.llm_provider import (
    ClaudeProviderClient,
    GeminiProviderClient,
    LLMRequest,
    LLMResponse,
    OpenAIProviderClient,
    strip_leading_reasoning_content,
)
from plugins.llm_runtime import LLMService, ResolvedGroupSettings
from plugins.llm_tools import LLMConversationMessage, LLMToolCall, LLMToolSpec
from plugins.message_stats import GroupStatsTracker
from plugins.message_deduper import RecentMessageDeduper
from plugins.message_rendering import render_message_for_llm
from plugins.recent_message_buffer import RecentMessageBuffer
from plugins.rule_switch import GroupRuleSwitch
from plugins.web_search import (
    SearXNGSearchClient,
    SearchResponse,
    SearchResult,
    TavilySearchClient,
    build_search_client,
    format_search_response,
)
from plugins.tavily_search import TavilySearchResponse, TavilySearchResult
from plugins.tz_tracker import _is_self_message


class DummySegment:
    def __init__(self, segment_type: str, data: dict):
        self.type = segment_type
        self.data = data


class DummyMessage(list):
    def __str__(self) -> str:
        parts = []
        for segment in self:
            if segment.type == "text":
                parts.append(segment.data.get("text", ""))
            elif segment.type == "at":
                parts.append(f"[CQ:at,qq={segment.data.get('qq', '')}]")
            elif segment.type == "image":
                parts.append("[CQ:image]")
        return "".join(parts)


class DummyEvent:
    def __init__(self, user_id, self_id):
        self.user_id = user_id
        self.self_id = self_id


class DummySender:
    def __init__(self, *, card="", nickname=""):
        self.card = card
        self.nickname = nickname


class DummyReply:
    def __init__(self, *, message, user_id, sender=None, message_id=None):
        self.message = message
        self.user_id = user_id
        self.sender = sender
        self.message_id = message_id


class StubProviderClient:
    last_request = None

    async def complete(self, request):
        StubProviderClient.last_request = request
        prompt = request.messages[-1].content if request.messages else ""
        return LLMResponse(
            text=f"stub::{request.model}::{prompt}",
            model=request.model,
            input_tokens=11,
            output_tokens=7,
        )


class StubToolCallingProviderClient:
    requests: list[LLMRequest] = []

    async def complete(self, request):
        StubToolCallingProviderClient.requests.append(request)
        if len(StubToolCallingProviderClient.requests) == 1:
            return LLMResponse(
                text="",
                model=request.model,
                tool_calls=[
                    LLMToolCall(
                        id="call_identity_1",
                        name="get_identity",
                        arguments_json='{"query":"哈基镜"}',
                    )
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(
            text="哈基镜通常指镜子。",
            model=request.model,
            finish_reason="stop",
        )


class StubMCPToolCallingProviderClient:
    requests: list[LLMRequest] = []

    async def complete(self, request):
        StubMCPToolCallingProviderClient.requests.append(request)
        if len(StubMCPToolCallingProviderClient.requests) == 1:
            return LLMResponse(
                text="",
                model=request.model,
                tool_calls=[
                    LLMToolCall(
                        id="call_mcp_1",
                        name="mcp_fake_echo_text",
                        arguments_json='{"text":"云端 DOOD"}',
                    )
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(
            text="echo::云端 DOOD",
            model=request.model,
            finish_reason="stop",
        )


class StubSearchOnlyProviderClient:
    requests: list[LLMRequest] = []

    async def complete(self, request):
        StubSearchOnlyProviderClient.requests.append(request)
        if len(StubSearchOnlyProviderClient.requests) <= 4:
            return LLMResponse(
                text="",
                model=request.model,
                tool_calls=[
                    LLMToolCall(
                        id=f"call_search_{len(StubSearchOnlyProviderClient.requests)}",
                        name="search_web",
                        arguments_json='{"query":"QuickQuip","topic":"general"}',
                    )
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(
            text="QuickQuip 是一个 QQ 群聊机器人项目。",
            model=request.model,
            finish_reason="stop",
        )


class FakeOpenAIClient(OpenAIProviderClient):
    def __init__(self, config: ProviderConfig, response_data: dict):
        config = ProviderConfig(**{**{f.name: getattr(config, f.name) for f in config.__dataclass_fields__.values()}, "stream_enabled": False})
        super().__init__(config)
        self.response_data = response_data
        self.last_payload = None

    async def _prepare_image_inputs(self, image_urls):
        return []

    def _get_api_key(self) -> str:
        return "test-key"

    async def _post_json(self, url, headers, payload):
        self.last_payload = payload
        return self.response_data


class FakeClaudeClient(ClaudeProviderClient):
    def __init__(self, config: ProviderConfig, response_data: dict):
        config = ProviderConfig(**{**{f.name: getattr(config, f.name) for f in config.__dataclass_fields__.values()}, "stream_enabled": False})
        super().__init__(config)
        self.response_data = response_data
        self.last_payload = None

    async def _prepare_image_inputs(self, image_urls):
        return []

    def _get_api_key(self) -> str:
        return "test-key"

    async def _post_json(self, url, headers, payload):
        self.last_payload = payload
        return self.response_data


class FakeGeminiClient(GeminiProviderClient):
    def __init__(self, config: ProviderConfig, response_data: dict):
        config = ProviderConfig(**{**{f.name: getattr(config, f.name) for f in config.__dataclass_fields__.values()}, "stream_enabled": False})
        super().__init__(config)
        self.response_data = response_data
        self.last_payload = None

    async def _prepare_image_inputs(self, image_urls):
        return []

    def _get_api_key(self) -> str:
        return "test-key"

    async def _post_json(self, url, headers, payload):
        self.last_payload = payload
        return self.response_data


class DummyAsyncWriter:
    def __init__(self):
        self.buffer = bytearray()

    def write(self, data: bytes):
        self.buffer.extend(data)

    async def drain(self):
        return None


class DummyAsyncReader:
    def __init__(self, *chunks: bytes):
        self.buffer = bytearray()
        for chunk in chunks:
            self.buffer.extend(chunk)

    async def readline(self) -> bytes:
        if not self.buffer:
            return b""
        try:
            newline_index = self.buffer.index(b"\n") + 1
        except ValueError:
            newline_index = len(self.buffer)
        data = bytes(self.buffer[:newline_index])
        del self.buffer[:newline_index]
        return data

    async def readexactly(self, count: int) -> bytes:
        if len(self.buffer) < count:
            partial = bytes(self.buffer)
            self.buffer.clear()
            raise asyncio.IncompleteReadError(partial=partial, expected=count)
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    async def read(self, count: int = -1) -> bytes:
        if count < 0 or count >= len(self.buffer):
            data = bytes(self.buffer)
            self.buffer.clear()
            return data
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data


class DummyProcess:
    def __init__(self, *, stdin=None, stdout=None, stderr=None):
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = 0


CONFIG_TEXT = textwrap.dedent(
    """
    [runtime]
    enabled = true
    default_provider = "openai-main"
    default_persona = "default"
    history_limit = 6
    history_max_messages_per_group = 8
    memory_limit = 3
    memory_max_items_per_group = 20
    max_prompt_chars = 1000
    tool_calling_enabled = true
    tool_max_rounds = 2
    tool_max_calls_per_round = 3

    [triggers]
    default_prefix = "/ai"
    allow_prefix = true
    allow_at = true
    empty_prompt_reply = "empty"

    [tools]
    enabled = []

    [[personas]]
    id = "default"
    display_name = "默认人格"
    system_prompt = "你是测试人格。"
    style_prompt = "短一点。"

    [[providers]]
    id = "openai-main"
    protocol = "openai"
    base_url = "https://example.test/v1"
    api_key_env = "OPENAI_API_KEY"
    default_model = "gpt-test"
    models = ["gpt-test", "gpt-alt"]
    timeout_seconds = 30
    temperature = 0.5
    max_output_tokens = 256
    """
).strip()

VOCAB_TEXT = textwrap.dedent(
    """
    核心成员:
      镜子: [镜千翎, 镜子, 哈基镜] # 特别注意不要和王者荣耀的镜混淆

    部分黑话解析: |
      区：群里常见的内部称谓，通常是熟人间的玩笑叫法。
    """
).strip()

IDENTITIES_TEXT = textwrap.dedent(
    """
    people:
      - canonical_name: 镜子
        qq_ids:
          - "2002"
        aliases:
          - 镜千翎
          - 哈基镜
        note: 特别注意不要和王者荣耀的镜混淆

      - canonical_name: 4s
        qq_ids: ["4004"]
        aliases: ["Туманность", "哈基四"]
        note: 大部分以四字开头的称呼通常指 4s
    """
).strip()

prefix_settings = ResolvedGroupSettings(
    enabled=True,
    memory_enabled=True,
    provider_id="openai-main",
    model="gpt-test",
    persona_id="default",
    trigger_prefix="/ai",
    allow_prefix=True,
    allow_at=True,
)

identity_artifact_dir = Path("dev/sandbox/test_artifacts/llm_identity_test")
if identity_artifact_dir.exists():
    shutil.rmtree(identity_artifact_dir)
identity_artifact_dir.mkdir(parents=True, exist_ok=True)
identity_path = identity_artifact_dir / "identities.yaml"
identity_path.write_text(IDENTITIES_TEXT, encoding="utf-8")
identity_index = IdentityIndex.from_file(identity_path)

prefix_message = DummyMessage([DummySegment("text", {"text": "/ai 你好"})])
assert extract_llm_prompt(prefix_message, "12345", prefix_settings) == "你好"

mention_message = DummyMessage(
    [
        DummySegment("at", {"qq": "12345"}),
        DummySegment("text", {"text": " 讲个笑话"}),
    ]
)
assert extract_llm_prompt(mention_message, "12345", prefix_settings) == "讲个笑话"
assert (
    extract_llm_prompt(
        DummyMessage([DummySegment("text", {"text": "来一句"} )]),
        "12345",
        prefix_settings,
        is_to_me=True,
    )
    == "来一句"
)

mention_user_message = DummyMessage(
    [
        DummySegment("text", {"text": "/ai 你看看"}),
        DummySegment("at", {"qq": "2002"}),
        DummySegment("text", {"text": " 今天又在说什么"}),
    ]
)
assert (
    extract_llm_prompt(
        mention_user_message,
        "12345",
        prefix_settings,
        identity_index=identity_index,
    )
    == "你看看@镜子 今天又在说什么"
)
rendered_recent = render_message_for_llm(
    mention_user_message,
    bot_self_id="12345",
    identity_index=identity_index,
    include_image_placeholder=True,
)
assert rendered_recent.text == "/ai 你看看@镜子 今天又在说什么"

image_message = DummyMessage(
    [
        DummySegment("text", {"text": "/ai"}),
        DummySegment("image", {"url": "https://example.test/cat.png"}),
    ]
)
image_input = extract_llm_input(image_message, "12345", prefix_settings)
assert image_input is not None
assert image_input.prompt == ""
assert image_input.image_urls == ["https://example.test/cat.png"]

quoted_reply = DummyReply(
    message=DummyMessage(
        [
            DummySegment("at", {"qq": "2002"}),
            DummySegment("text", {"text": " 这张图什么意思"}),
            DummySegment("image", {"url": "https://example.test/reply-cat.png"}),
        ]
    ),
    user_id="2002",
    sender=DummySender(nickname="镜子"),
    message_id=7788,
)
quoted_input = extract_llm_input(
    DummyMessage(
        [
            DummySegment("at", {"qq": "12345"}),
            DummySegment("text", {"text": " 帮我看看"}),
        ]
    ),
    "12345",
    prefix_settings,
    identity_index=identity_index,
    reply=quoted_reply,
)
assert quoted_input is not None
assert quoted_input.prompt == "帮我看看"
assert quoted_input.quoted_text == "@镜子 这张图什么意思[图片]"
assert quoted_input.quoted_image_urls == ["https://example.test/reply-cat.png"]
assert quoted_input.quoted_sender_name == "镜子"
assert quoted_input.quoted_user_id == "2002"

non_trigger_message = DummyMessage([DummySegment("text", {"text": "普通消息"})])
assert extract_llm_prompt(non_trigger_message, "12345", prefix_settings) is None

private_free_text_input = extract_private_llm_input(
    DummyMessage([DummySegment("text", {"text": "普通私聊消息"})]),
    "12345",
    prefix_settings,
)
assert private_free_text_input is not None
assert private_free_text_input.prompt == "普通私聊消息"

private_image_input = extract_private_llm_input(
    DummyMessage([DummySegment("image", {"url": "https://example.test/private-cat.png"})]),
    "12345",
    prefix_settings,
)
assert private_image_input is not None
assert private_image_input.prompt == ""
assert private_image_input.image_urls == ["https://example.test/private-cat.png"]

private_reply_input = extract_private_llm_input(
    DummyMessage([DummySegment("text", {"text": "帮我接着说"})]),
    "12345",
    prefix_settings,
    identity_index=identity_index,
    reply=quoted_reply,
)
assert private_reply_input is not None
assert private_reply_input.prompt == "帮我接着说"
assert private_reply_input.quoted_text == "@镜子 这张图什么意思[图片]"

recent_buffer = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
for index in range(25):
    recent_buffer.add_message(1, index, f"用户{index}", f"标准名{index}", f"消息{index}", now_ts=index)
recent_items = recent_buffer.list_recent(1, now_ts=25)
assert len(recent_items) == 20
assert recent_items[0]["text"] == "消息5"
assert recent_items[-1]["text"] == "消息24"
assert recent_items[-1]["canonical_name"] == "标准名24"
assert recent_buffer.list_recent(1, now_ts=90) == []

deduper = RecentMessageDeduper(max_ids_per_group=2)
assert deduper.is_duplicate(1, 10001) is False
assert deduper.is_duplicate(1, 10001) is True
assert deduper.is_duplicate(1, 10002) is False
assert deduper.is_duplicate(1, 10003) is False
assert deduper.is_duplicate(1, 10001) is False

stdio_client = StdioMCPClient(MCPServerConfig(id="stdio-test"))
stdio_writer = DummyAsyncWriter()
stdio_client.process = DummyProcess(
    stdin=stdio_writer,
    stdout=DummyAsyncReader(),
    stderr=DummyAsyncReader(),
)
asyncio.run(
    stdio_client._send_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        }
    )
)
sent_text = stdio_writer.buffer.decode("utf-8")
assert "Content-Length" not in sent_text
assert sent_text.endswith("\n")
assert json.loads(sent_text.strip())["method"] == "initialize"

line_message = b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n'
stdio_client.process = DummyProcess(
    stdin=DummyAsyncWriter(),
    stdout=DummyAsyncReader(line_message),
    stderr=DummyAsyncReader(),
)
assert asyncio.run(stdio_client._read_message()) == {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {"ok": True},
}

header_payload = b'{"jsonrpc":"2.0","id":2,"result":{"ok":true}}'
header_message = (
    f"Content-Length: {len(header_payload)}\r\nX-Test: 1\r\n\r\n".encode("ascii") + header_payload
)
stdio_client.process = DummyProcess(
    stdin=DummyAsyncWriter(),
    stdout=DummyAsyncReader(header_message),
    stderr=DummyAsyncReader(),
)
assert asyncio.run(stdio_client._read_message()) == {
    "jsonrpc": "2.0",
    "id": 2,
    "result": {"ok": True},
}

assert _is_self_message(DummyEvent(user_id=12345, self_id=12345)) is True
assert _is_self_message(DummyEvent(user_id=12345, self_id=54321)) is False

artifact_dir = Path("dev/sandbox/test_artifacts/llm_test")
if artifact_dir.exists():
    shutil.rmtree(artifact_dir)
artifact_dir.mkdir(parents=True, exist_ok=True)

config_path = artifact_dir / "llm.toml"
db_path = artifact_dir / "llm.db"
vocab_path = artifact_dir / "vocab.yaml"
service_identity_path = artifact_dir / "identities.yaml"
config_path.write_text(CONFIG_TEXT, encoding="utf-8")
vocab_path.write_text(VOCAB_TEXT, encoding="utf-8")
service_identity_path.write_text(IDENTITIES_TEXT, encoding="utf-8")

service = LLMService(
    config_path=config_path,
    db_path=db_path,
    vocab_path=vocab_path,
    identity_path=service_identity_path,
)
service_stats = GroupStatsTracker()
service_stats.record_message(1001, "2002", "镜子")
service_stats.record_message(1001, "4004", "4s")
service_stats.record_message(1001, "2002", "镜子")
service_stats.record_trigger(1001, "divine_arrival")
service_stats.record_trigger(1001, "divine_arrival")
service_rule_switch = GroupRuleSwitch()
service_rule_switch.disable(1001, "play_target")
service_recent_messages = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
service_recent_messages.add_message(1001, "2002", "乙", "镜子", "@4s 哈基镜今天又在发病。")
service_recent_messages.add_message(1001, "4004", "丙", "4s", "刚才谁在神临。")
service.bind_group_stats_tracker(service_stats)
service.bind_rule_switch(service_rule_switch)
service.bind_recent_message_buffer(service_recent_messages)
assert service.config.load_error is None
assert service.format_status(1001).startswith("LLM 状态")

service.set_group_model(1001, "openai-main", "gpt-alt")
service.set_group_persona(1001, "default")
service.set_group_trigger_prefix(1001, "/bot")
service.set_group_allow_at(1001, False)
service.set_group_allow_prefix(1001, True)
service.set_chat_persona(3003, "default", chat_type="private")
service.set_chat_trigger_prefix(3003, "/dm", chat_type="private")
service.set_chat_allow_prefix(3003, True, chat_type="private")

status = service.format_status(1001)
assert "Model：gpt-alt" in status
assert "(/bot)" in status
assert "艾特触发：OFF" in status
assert "临时上下文：触发前最多 20 条群消息" in status
assert "记忆注入：ON" in status
assert "工具调用：ON" in status

private_settings = service.get_chat_settings(3003, chat_type="private")
assert private_settings.enabled is False
assert private_settings.allow_at is False
private_status = service.format_status(3003, chat_type="private")
assert "当前会话：私聊" in private_status
assert "总开关：OFF" in private_status
assert "前缀触发：ON (/dm)" in private_status
assert "会话状态：未开启" in private_status
assert "直聊触发：仅在会话开启后生效" in private_status
assert "艾特触发：OFF（私聊不适用）" in private_status
assert "临时上下文：私聊不额外注入群消息" in private_status

current = service.format_current(1001)
assert current.startswith("LLM 当前配置")
assert "短期会话：已存 0 条" in current
assert "长期记忆：已存 0 条" in current
assert "工具列表：" in current
for tool_name in (
    "get_identity",
    "list_memories",
    "search_web",
    "get_group_stats",
    "get_rule_status",
    "search_recent_messages",
    "get_llm_status",
    "get_current_model",
):
    assert tool_name in current

private_current = service.format_current(3003, chat_type="private")
assert "当前会话：私聊" in private_current
assert "会话状态：未开启" in private_current
assert "直聊触发：仅在会话开启后生效" in private_current
assert "短期会话：已存 0 条 / 读取上限 256 条（默认 256）" in private_current
assert "get_group_stats" not in private_current
assert "get_rule_status" not in private_current

memory_id = service.remember_group_memory(1001, "阿桃喜欢薄荷糖。")
assert memory_id >= 1
memories = service.list_group_memories(1001)
assert memories[0]["content"] == "阿桃喜欢薄荷糖。"
assert "阿桃喜欢薄荷糖。" in service.format_memories(1001)
matched_memories = service.store.search_memories(1001, user_id=2002, query="阿桃喜欢什么？", limit=3)
assert matched_memories
assert matched_memories[0]["content"] == "阿桃喜欢薄荷糖。"
memory_status = service.format_memory_status(1001)
assert "记忆注入：ON" in memory_status
assert "已存条数：1" in memory_status

private_memory_id = service.remember_memory(3003, "阿桃在私聊里更愿意长篇回复。", chat_type="private")
assert private_memory_id >= 1
private_memories = service.list_memories(3003, chat_type="private")
assert private_memories[0]["content"] == "阿桃在私聊里更愿意长篇回复。"
assert "当前私聊记忆" in service.format_memories(3003, chat_type="private")
private_memory_status = service.format_memory_status(3003, chat_type="private")
assert "当前会话：私聊" in private_memory_status
assert "已存条数：1" in private_memory_status

private_memory_matches = service.store.search_memories(
    service.build_chat_scope_key(3003, chat_type="private"),
    user_id=3003,
    query="私聊时你会怎么回复？",
    limit=3,
)
assert private_memory_matches
assert private_memory_matches[0]["content"] == "阿桃在私聊里更愿意长篇回复。"
service.start_private_session(3003)
assert service.get_chat_settings(3003, chat_type="private").enabled is True
assert "会话状态：进行中" in service.format_status(3003, chat_type="private")

service.set_group_memory_enabled(1001, False)
memory_status_off = service.format_memory_status(1001)
assert "记忆注入：OFF" in memory_status_off
service.set_group_memory_enabled(1001, True)

original_builder = llm_runtime_module.build_provider_client
llm_runtime_module.build_provider_client = lambda provider: StubProviderClient()
try:
    result = asyncio.run(
        service.generate_reply(
            group_id=1001,
            user_id=2002,
            sender_name="测试用户",
            prompt="哈基镜是区吗？",
            recent_messages=[
                {"user_id": "u1", "sender_name": "甲", "canonical_name": "", "text": "昨晚排位真红温。"},
                {
                    "user_id": "2002",
                    "sender_name": "乙",
                    "canonical_name": "镜子",
                    "text": "@4s 哈基镜今天又在发病。",
                },
            ],
        )
    )
finally:
    llm_runtime_module.build_provider_client = original_builder

assert result["rule_name"] == "llm_chat"
assert result["reply"] == "stub::gpt-alt::哈基镜是区吗？"
assert StubProviderClient.last_request is not None
assert "当前元数据：" in StubProviderClient.last_request.system_prompt
assert "当前北京时间：" in StubProviderClient.last_request.system_prompt
assert "当前星期：" in StubProviderClient.last_request.system_prompt
assert "当前提问者身份：" in StubProviderClient.last_request.system_prompt
assert "- QQ：2002" in StubProviderClient.last_request.system_prompt
assert "- 标准身份：镜子" in StubProviderClient.last_request.system_prompt
assert "当前已知参与者：" in StubProviderClient.last_request.system_prompt
assert "- 镜子（QQ 2002，当前显示名：测试用户）" in StubProviderClient.last_request.system_prompt
assert "- 甲（QQ u1，未登记）" in StubProviderClient.last_request.system_prompt
assert "常见别名：镜千翎、哈基镜" in StubProviderClient.last_request.system_prompt
assert "哈基镜 通常指 镜子" in StubProviderClient.last_request.system_prompt
assert "不要和王者荣耀的镜混淆" in StubProviderClient.last_request.system_prompt
assert "区：群里常见的内部称谓" in StubProviderClient.last_request.system_prompt
assert StubProviderClient.last_request.messages[0].content.startswith("以下是本次触发前")
assert "甲（QQ u1，未登记）：昨晚排位真红温。" in StubProviderClient.last_request.messages[0].content
assert "镜子（QQ 2002，当前显示名：乙）：@4s 哈基镜今天又在发病。" in StubProviderClient.last_request.messages[0].content
assert StubProviderClient.last_request.messages[-1].content == "哈基镜是区吗？"
assert StubProviderClient.last_request.messages[-1].image_urls == []
assert all(
    item.content != "哈基镜是区吗？"
    for item in StubProviderClient.last_request.messages[:-1]
)
assert {tool.name for tool in StubProviderClient.last_request.tools} == {
    "get_identity",
    "list_memories",
    "search_web",
    "get_group_stats",
    "get_rule_status",
    "search_recent_messages",
    "get_llm_status",
    "get_current_model",
}

llm_runtime_module.build_provider_client = lambda provider: StubProviderClient()
try:
    quoted_result = asyncio.run(
        service.generate_reply(
            group_id=1002,
            user_id=3003,
            sender_name="测试用户",
            prompt="帮我看看",
            image_urls=[],
            quoted_text="@镜子 这张图什么意思[图片]",
            quoted_image_urls=["https://example.test/reply-cat.png"],
            quoted_sender_name="镜子",
            quoted_user_id="2002",
        )
)
finally:
    llm_runtime_module.build_provider_client = original_builder

assert quoted_result["reply"].startswith("stub::gpt-test::以下是当前用户显式引用的消息")
assert "引用发送者：镜子（QQ 2002）" in StubProviderClient.last_request.messages[-1].content
assert "引用内容：@镜子 这张图什么意思[图片]" in StubProviderClient.last_request.messages[-1].content
assert "当前用户消息：" in StubProviderClient.last_request.messages[-1].content
assert "帮我看看" in StubProviderClient.last_request.messages[-1].content
assert StubProviderClient.last_request.messages[-1].image_urls == ["https://example.test/reply-cat.png"]

service.store.append_conversation_message(
    1003,
    "2002",
    "user",
    "我觉得 4s 今天说得对。",
    sender_name="镜千翎",
    canonical_name="镜子",
)
service.store.append_conversation_message(1003, None, "assistant", "你说的是哪句？")
service.store.append_conversation_message(
    1003,
    "4004",
    "user",
    "不是我刚才说的，是镜子先提的。",
    sender_name="Туманность",
    canonical_name="4s",
)
llm_runtime_module.build_provider_client = lambda provider: StubProviderClient()
try:
    multi_user_result = asyncio.run(
        service.generate_reply(
            group_id=1003,
            user_id=2002,
            sender_name="镜千翎",
            prompt="你现在要分清刚才是谁说的。",
            recent_messages=[],
        )
    )
finally:
    llm_runtime_module.build_provider_client = original_builder

assert multi_user_result["reply"] == "stub::gpt-test::你现在要分清刚才是谁说的。"
assert "当前已知参与者：" in StubProviderClient.last_request.system_prompt
assert "- 镜子（QQ 2002，当前显示名：镜千翎）" in StubProviderClient.last_request.system_prompt
assert "- 4s（QQ 4004，当前显示名：Туманность）" in StubProviderClient.last_request.system_prompt
assert StubProviderClient.last_request.messages[0].content.startswith("历史会话消息")
assert "发言者：镜子（QQ 2002，当前显示名：镜千翎）" in StubProviderClient.last_request.messages[0].content
assert "内容：我觉得 4s 今天说得对。" in StubProviderClient.last_request.messages[0].content
assert StubProviderClient.last_request.messages[2].content.startswith("历史会话消息")
assert "发言者：4s（QQ 4004，当前显示名：Туманность）" in StubProviderClient.last_request.messages[2].content
assert "内容：不是我刚才说的，是镜子先提的。" in StubProviderClient.last_request.messages[2].content

private_scope_key = service.build_chat_scope_key(3003, chat_type="private")
for index in range(50):
    service.store.append_conversation_message(
        private_scope_key,
        "3003" if index % 2 == 0 else None,
        "user" if index % 2 == 0 else "assistant",
        f"私聊历史{index}",
        sender_name="阿桃" if index % 2 == 0 else "",
    )

llm_runtime_module.build_provider_client = lambda provider: StubProviderClient()
try:
    private_result = asyncio.run(
        service.generate_private_reply(
            user_id=3003,
            sender_name="阿桃",
            prompt="私聊里继续我们刚才的话题",
        )
    )
finally:
    llm_runtime_module.build_provider_client = original_builder

assert private_result["reply"] == "stub::gpt-test::私聊里继续我们刚才的话题"
assert "当前会话类型：私聊" in StubProviderClient.last_request.system_prompt
assert "当前私聊对象 QQ：3003" in StubProviderClient.last_request.system_prompt
assert "当前处于一对一私聊场景" in StubProviderClient.last_request.system_prompt
assert "阿桃在私聊里更愿意长篇回复。" in StubProviderClient.last_request.system_prompt
assert len(StubProviderClient.last_request.messages) == 51
assert StubProviderClient.last_request.messages[0].content.startswith("历史会话消息")
assert "发言者：阿桃（QQ 3003，未登记）" in StubProviderClient.last_request.messages[0].content
assert "内容：私聊历史0" in StubProviderClient.last_request.messages[0].content
assert StubProviderClient.last_request.messages[-1].content == "私聊里继续我们刚才的话题"
assert StubProviderClient.last_request.messages[-1].image_urls == []
assert service.store.count_conversation_messages(private_scope_key) == 52
private_deleted_context = service.end_private_session(3003)
assert private_deleted_context["deleted"] == 52
assert service.get_chat_settings(3003, chat_type="private").enabled is False
assert service.store.list_recent_conversation_messages(private_scope_key, 100) == []
assert "会话状态：未开启" in service.format_status(3003, chat_type="private")

history = service.store.list_recent_conversation_messages(1001, 10)
assert history[-2]["role"] == "user"
assert history[-2]["content"] == "哈基镜是区吗？"
assert history[-2]["user_id"] == "2002"
assert history[-2]["sender_name"] == "测试用户"
assert history[-2]["canonical_name"] == "镜子"
assert history[-1]["role"] == "assistant"
assert history[-1]["content"] == "stub::gpt-alt::哈基镜是区吗？"
assert "短期会话：已存 2 条" in service.format_current(1001)

for index in range(20):
    service.store.append_conversation_message(1001, "u", "assistant", f"补充{index}")
effective_history_cap = min(service.config.runtime.history_max_messages_per_group, 20)
service.store.prune_conversation_messages(1001, effective_history_cap)
pruned_history = service.store.list_recent_conversation_messages(1001, 100)
assert len(pruned_history) == effective_history_cap
deleted_context = service.clear_group_context(1001)
assert deleted_context == effective_history_cap
assert service.store.list_recent_conversation_messages(1001, 100) == []

deleted = service.forget_group_memories(1001, "薄荷糖")
assert deleted == 1
assert service.list_group_memories(1001) == []

tool_context_result = asyncio.run(
    service._tool_get_identity({"query": "哈基镜"}, service_context := llm_runtime_module.ToolExecutionContext(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        provider_id="openai-main",
        model="gpt-alt",
    ))
)
assert "标准身份：镜子" in tool_context_result
assert "QQ：2002" in tool_context_result

tool_group_stats = asyncio.run(service._tool_get_group_stats({}, service_context))
assert "当前群统计：" in tool_group_stats
assert "消息总数：3" in tool_group_stats
assert "镜子（QQ 2002）— 2 条" in tool_group_stats
assert "divine_arrival — 2 次" in tool_group_stats

tool_rule_status = asyncio.run(service._tool_get_rule_status({}, service_context))
assert "当前群已关闭规则" in tool_rule_status
assert "- play_target" in tool_rule_status
tool_single_rule_status = asyncio.run(
    service._tool_get_rule_status({"rule_name": "play_target"}, service_context)
)
assert tool_single_rule_status == "规则状态：play_target = OFF"

tool_recent_messages = asyncio.run(
    service._tool_search_recent_messages({"query": "哈基镜", "limit": 3}, service_context)
)
assert "最近消息检索：哈基镜" in tool_recent_messages
assert "镜子（QQ 2002，当前显示名：乙）" in tool_recent_messages

tool_llm_status = asyncio.run(service._tool_get_llm_status({}, service_context))
assert tool_llm_status.startswith("LLM 状态")
tool_llm_current = asyncio.run(service._tool_get_llm_status({"detail": "current"}, service_context))
assert tool_llm_current.startswith("LLM 当前配置")

tool_current_model = asyncio.run(service._tool_get_current_model({}, service_context))
assert "当前群模型配置：" in tool_current_model
assert "- Provider：openai-main" in tool_current_model
assert "- Model：gpt-alt" in tool_current_model
assert "- Persona：default" in tool_current_model

private_context = llm_runtime_module.ToolExecutionContext(
    group_id=3003,
    user_id=3003,
    sender_name="阿桃",
    provider_id="openai-main",
    model="gpt-test",
    chat_scope=private_scope_key,
    chat_type="private",
)
service_recent_messages.add_message(private_scope_key, "3003", "阿桃", "阿桃", "/dm 继续我们刚才的话题")

tool_private_memories = asyncio.run(service._tool_list_memories({}, private_context))
assert "当前私聊记忆：" in tool_private_memories
assert "阿桃在私聊里更愿意长篇回复。" in tool_private_memories
tool_private_recent = asyncio.run(
    service._tool_search_recent_messages({"query": "刚才", "limit": 3}, private_context)
)
assert "最近私聊消息检索：刚才" in tool_private_recent
tool_private_status = asyncio.run(service._tool_get_llm_status({}, private_context))
assert "当前会话：私聊" in tool_private_status
tool_private_model = asyncio.run(service._tool_get_current_model({}, private_context))
assert "当前私聊模型配置：" in tool_private_model
assert "艾特触发：OFF（私聊不适用）" in tool_private_model
assert asyncio.run(service._tool_get_group_stats({}, private_context)) == "当前私聊没有群消息统计。"
assert asyncio.run(service._tool_get_rule_status({}, private_context)) == "当前私聊没有群规则开关。"

StubToolCallingProviderClient.requests = []
llm_runtime_module.build_provider_client = lambda provider: StubToolCallingProviderClient()
try:
    tool_loop_result = asyncio.run(
        service.generate_reply(
            group_id=1001,
            user_id=2002,
            sender_name="测试用户",
            prompt="哈基镜是谁？",
            recent_messages=[],
        )
    )
finally:
    llm_runtime_module.build_provider_client = original_builder

assert tool_loop_result["reply"] == "哈基镜通常指镜子。"
assert len(StubToolCallingProviderClient.requests) == 2
second_request = StubToolCallingProviderClient.requests[-1]
assert second_request.messages[-2].role == "assistant"
assert second_request.messages[-2].tool_calls[0].name == "get_identity"
assert second_request.messages[-1].role == "tool"
assert second_request.messages[-1].tool_name == "get_identity"
assert "标准身份：镜子" in second_request.messages[-1].content

mcp_artifact_dir = Path("dev/sandbox/test_artifacts/llm_mcp_test")
if mcp_artifact_dir.exists():
    shutil.rmtree(mcp_artifact_dir)
mcp_artifact_dir.mkdir(parents=True, exist_ok=True)

mcp_config_path = mcp_artifact_dir / "llm.toml"
mcp_db_path = mcp_artifact_dir / "llm.db"
mcp_vocab_path = mcp_artifact_dir / "vocab.yaml"
mcp_identity_path = mcp_artifact_dir / "identities.yaml"
mcp_vocab_path.write_text(VOCAB_TEXT, encoding="utf-8")
mcp_identity_path.write_text(IDENTITIES_TEXT, encoding="utf-8")

mcp_config_text = textwrap.dedent(
    """
    [runtime]
    enabled = true
    default_provider = "openai-main"
    default_persona = "default"
    history_limit = 6
    history_max_messages_per_group = 8
    memory_limit = 3
    memory_max_items_per_group = 20
    max_prompt_chars = 1000
    tool_calling_enabled = true
    tool_max_rounds = 2
    tool_max_calls_per_round = 3

    [triggers]
    default_prefix = "/ai"
    allow_prefix = true
    allow_at = true
    empty_prompt_reply = "empty"

    [tools]
    enabled = []

    [mcp]
    enabled = true

    [[mcp.servers]]
    id = "fake"
    transport = "stdio"
    command = "python"
    args = ["fake_mcp_server.py"]
    timeout_seconds = 10

    [[personas]]
    id = "default"
    display_name = "默认人格"
    system_prompt = "你是测试人格。"
    style_prompt = "短一点。"

    [[providers]]
    id = "openai-main"
    protocol = "openai"
    base_url = "https://example.test/v1"
    api_key_env = "OPENAI_API_KEY"
    default_model = "gpt-test"
    models = ["gpt-test"]
    timeout_seconds = 30
    temperature = 0.5
    max_output_tokens = 256
    """
).strip()
mcp_config_path.write_text(mcp_config_text, encoding="utf-8")

mcp_service = LLMService(
    config_path=mcp_config_path,
    db_path=mcp_db_path,
    vocab_path=mcp_vocab_path,
    identity_path=mcp_identity_path,
)
async def _fake_mcp_sync(_config):
    binding = MCPToolBinding(
        alias="mcp_fake_echo_text",
        server_id="fake",
        tool_name="echo_text",
        description="回显输入文本。",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    mcp_service.mcp_manager._statuses = {
        "fake": MCPServerStatus(
            id="fake",
            transport="stdio",
            enabled=True,
            connected=True,
            tool_count=1,
            detail="fake-mcp 1.0.0",
        )
    }
    mcp_service.mcp_manager._bindings = {binding.alias: binding}
    return [binding]


async def _fake_mcp_execute(alias, arguments, context):
    _ = alias, context
    return f"echo::{arguments['text']}"


mcp_service.mcp_manager.sync = _fake_mcp_sync
mcp_service.mcp_manager.execute = _fake_mcp_execute
asyncio.run(mcp_service.startup())
assert "连接数：1/1" in mcp_service.format_mcp_status()
assert "工具数：1" in mcp_service.format_mcp_status()
assert "MCP：ON (1/1，1 tools)" in mcp_service.format_current(2001)
assert "mcp_fake_echo_text" in mcp_service.format_current(2001)

original_builder = llm_runtime_module.build_provider_client
StubMCPToolCallingProviderClient.requests = []
llm_runtime_module.build_provider_client = lambda provider: StubMCPToolCallingProviderClient()
try:
    mcp_result = asyncio.run(
        mcp_service.generate_reply(
            group_id=2001,
            user_id=2002,
            sender_name="测试用户",
            prompt="帮我走 MCP 工具",
            recent_messages=[],
        )
    )
finally:
    llm_runtime_module.build_provider_client = original_builder
    asyncio.run(mcp_service.shutdown())

assert mcp_result["reply"] == "echo::云端 DOOD"
assert len(StubMCPToolCallingProviderClient.requests) == 2
mcp_second_request = StubMCPToolCallingProviderClient.requests[-1]
assert mcp_second_request.messages[-2].tool_calls[0].name == "mcp_fake_echo_text"
assert mcp_second_request.messages[-1].role == "tool"
assert mcp_second_request.messages[-1].tool_name == "mcp_fake_echo_text"
assert mcp_second_request.messages[-1].content == "echo::云端 DOOD"

env_expand_dir = Path("dev/sandbox/test_artifacts/llm_env_expand_test")
if env_expand_dir.exists():
    shutil.rmtree(env_expand_dir)
env_expand_dir.mkdir(parents=True, exist_ok=True)
env_expand_config = env_expand_dir / "llm.toml"
env_expand_config.write_text(
    textwrap.dedent(
        """
        [runtime]
        enabled = "${QQ_TEST_ENABLED:-true}"
        default_provider = "openai-main"
        default_persona = "default"
        tool_calling_enabled = "${QQ_TOOL_CALLING_ENABLED:-true}"

        [mcp]
        enabled = "${QQ_MCP_ENABLED:-true}"

        [[mcp.servers]]
        id = "expand"
        transport = "docker"
        enabled = "${QQ_MCP_SERVER_ENABLED:-true}"
        image = "ghcr.io/example/server:latest"
        mounts = ["${QQ_MCP_MOUNT_ONE:-/data/one:/mnt/one:ro}", "${QQ_MCP_MOUNT_TWO:-}"]
        mount_docker_socket = "${QQ_MCP_SOCKET:-true}"

        [[personas]]
        id = "default"
        display_name = "默认人格"
        system_prompt = "你是测试人格。"

        [[providers]]
        id = "openai-main"
        protocol = "openai"
        base_url = "https://example.test/v1"
        api_key_env = "OPENAI_API_KEY"
        default_model = "gpt-test"
        models = ["gpt-test"]
        """
    ).strip(),
    encoding="utf-8",
)
os.environ["QQ_TEST_ENABLED"] = "true"
os.environ["QQ_TOOL_CALLING_ENABLED"] = "true"
os.environ["QQ_MCP_ENABLED"] = "true"
os.environ["QQ_MCP_SERVER_ENABLED"] = "true"
os.environ["QQ_MCP_SOCKET"] = "true"
env_expand_loaded = llm_runtime_module.load_llm_config(env_expand_config)
assert env_expand_loaded.runtime.enabled is True
assert env_expand_loaded.runtime.tool_calling_enabled is True
assert env_expand_loaded.mcp.enabled is True
assert env_expand_loaded.mcp.servers[0].enabled is True
assert env_expand_loaded.mcp.servers[0].mount_docker_socket is True
assert env_expand_loaded.mcp.servers[0].mounts == ["/data/one:/mnt/one:ro"]

search_reply = format_search_response(
    TavilySearchResponse(
        query="QuickQuip",
        answer="这是一个 QQ 群聊机器人项目。",
        results=[
            TavilySearchResult(
                title="QuickQuip README",
                url="https://example.test/quickquip",
                content="QuickQuip 是一个基于 NoneBot2 的 QQ 群聊机器人。",
            )
        ],
    )
)
assert "联网搜索：QuickQuip" in search_reply
assert "摘要：这是一个 QQ 群聊机器人项目。" in search_reply
assert "https://example.test/quickquip" in search_reply

old_search_backend = os.environ.get("SEARCH_BACKEND")
old_searxng_base_url = os.environ.get("SEARXNG_BASE_URL")
try:
    os.environ.pop("SEARCH_BACKEND", None)
    os.environ.pop("SEARXNG_BASE_URL", None)
    assert isinstance(build_search_client(), TavilySearchClient)

    os.environ["SEARXNG_BASE_URL"] = "http://127.0.0.1:8888"
    assert isinstance(build_search_client(), SearXNGSearchClient)

    os.environ["SEARCH_BACKEND"] = "tavily"
    assert isinstance(build_search_client(), TavilySearchClient)
finally:
    if old_search_backend is None:
        os.environ.pop("SEARCH_BACKEND", None)
    else:
        os.environ["SEARCH_BACKEND"] = old_search_backend
    if old_searxng_base_url is None:
        os.environ.pop("SEARXNG_BASE_URL", None)
    else:
        os.environ["SEARXNG_BASE_URL"] = old_searxng_base_url


class FakeSearchHTTPResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


captured_search_requests = []
original_urlopen = web_search_module.request.urlopen


def fake_search_urlopen(http_request, timeout):
    captured_search_requests.append((http_request.full_url, timeout))
    return FakeSearchHTTPResponse(
        {
            "query": "QuickQuip",
            "results": [
                {
                    "title": "QuickQuip README",
                    "url": "https://example.test/quickquip",
                    "content": "QuickQuip 是一个基于 NoneBot2 的 QQ 群聊机器人。",
                    "score": 0.9,
                }
            ],
        }
    )


web_search_module.request.urlopen = fake_search_urlopen
try:
    searxng_response = asyncio.run(
        SearXNGSearchClient(instance_url="http://127.0.0.1:8888").search(
            "QuickQuip",
            topic="news",
            max_results=2,
        )
    )
finally:
    web_search_module.request.urlopen = original_urlopen

assert captured_search_requests
assert "format=json" in captured_search_requests[0][0]
assert "categories=news" in captured_search_requests[0][0]
assert "q=QuickQuip" in captured_search_requests[0][0]
assert searxng_response == SearchResponse(
    query="QuickQuip",
    answer=None,
    results=[
        SearchResult(
            title="QuickQuip README",
            url="https://example.test/quickquip",
            content="QuickQuip 是一个基于 NoneBot2 的 QQ 群聊机器人。",
            score=0.9,
        )
    ],
    response_time=None,
    request_id=None,
)


class FakeToolSearchClient:
    async def search(self, query, *, topic="general", max_results=5):
        assert query == "QuickQuip"
        assert topic == "general"
        assert max_results == 5
        return SearchResponse(
            query=query,
            answer="这是一个 QQ 群聊机器人项目。",
            results=[
                SearchResult(
                    title="QuickQuip README",
                    url="https://example.test/quickquip",
                    content="QuickQuip 是一个基于 NoneBot2 的 QQ 群聊机器人。",
                )
            ],
        )


old_search_backend = os.environ.get("SEARCH_BACKEND")
old_searxng_base_url = os.environ.get("SEARXNG_BASE_URL")
original_builder = llm_runtime_module.build_provider_client
original_search_builder = llm_runtime_module.build_search_client
StubSearchOnlyProviderClient.requests = []
os.environ["SEARCH_BACKEND"] = "searxng"
os.environ["SEARXNG_BASE_URL"] = "http://127.0.0.1:8888"
llm_runtime_module.build_provider_client = lambda provider: StubSearchOnlyProviderClient()
llm_runtime_module.build_search_client = lambda: FakeToolSearchClient()
try:
    search_loop_result = asyncio.run(
        service.generate_reply(
            group_id=1001,
            user_id=2002,
            sender_name="测试用户",
            prompt="QuickQuip 是什么？",
            recent_messages=[],
        )
    )
finally:
    llm_runtime_module.build_provider_client = original_builder
    llm_runtime_module.build_search_client = original_search_builder
    if old_search_backend is None:
        os.environ.pop("SEARCH_BACKEND", None)
    else:
        os.environ["SEARCH_BACKEND"] = old_search_backend
    if old_searxng_base_url is None:
        os.environ.pop("SEARXNG_BASE_URL", None)
    else:
        os.environ["SEARXNG_BASE_URL"] = old_searxng_base_url

assert search_loop_result["reply"] == "QuickQuip 是一个 QQ 群聊机器人项目。"
assert len(StubSearchOnlyProviderClient.requests) == 5
assert "当前联网后端：SearXNG。" in StubSearchOnlyProviderClient.requests[0].system_prompt
assert "可以继续多次调用 search_web 细化检索" in StubSearchOnlyProviderClient.requests[0].system_prompt

llm_runtime_module.build_provider_client = lambda provider: StubProviderClient()
try:
    vision_result = asyncio.run(
        service.generate_reply(
            group_id=1002,
            user_id=3003,
            sender_name="测试用户",
            prompt="",
            image_urls=["https://example.test/cat.png"],
        )
    )
finally:
    llm_runtime_module.build_provider_client = original_builder

assert vision_result["reply"] == "stub::gpt-test::请描述这张图片，并优先回答群友最可能想知道的内容。"
assert StubProviderClient.last_request.messages[-1].image_urls == ["https://example.test/cat.png"]
assert StubProviderClient.last_request.messages[-1].content.startswith("请描述这张图片")

provider_request = LLMRequest(
    model="gpt-test",
    system_prompt="系统提示",
    messages=[LLMConversationMessage(role="user", content="查一下", image_urls=[])],
    temperature=0.2,
    max_output_tokens=128,
    tools=[
        LLMToolSpec(
            name="get_identity",
            description="身份查询",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ],
    allow_tool_calls=True,
)

fake_provider_config = ProviderConfig(
    id="fake",
    protocol="openai",
    base_url="https://example.test/v1",
    api_key_env="OPENAI_API_KEY",
    default_model="gpt-test",
    models=["gpt-test"],
)

openai_client = FakeOpenAIClient(
    fake_provider_config,
    {
        "model": "gpt-test",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "tool_openai_1",
                            "type": "function",
                            "function": {
                                "name": "get_identity",
                                "arguments": '{"query":"哈基镜"}',
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    },
)
openai_response = asyncio.run(openai_client.complete(provider_request))
assert openai_client.last_payload["tools"][0]["function"]["name"] == "get_identity"
assert openai_response.tool_calls[0].name == "get_identity"
assert openai_response.tool_calls[0].arguments_json == '{"query":"哈基镜"}'

claude_client = FakeClaudeClient(
    ProviderConfig(
        id="fake-claude",
        protocol="claude",
        base_url="https://example.test/v1",
        api_key_env="ANTHROPIC_API_KEY",
        default_model="claude-test",
        models=["claude-test"],
    ),
    {
        "model": "claude-test",
        "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": ""},
            {
                "type": "tool_use",
                "id": "tool_claude_1",
                "name": "get_identity",
                "input": {"query": "哈基镜"},
            },
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    },
)
claude_response = asyncio.run(claude_client.complete(provider_request))
assert claude_client.last_payload["tools"][0]["name"] == "get_identity"
assert claude_response.tool_calls[0].name == "get_identity"
assert claude_response.tool_calls[0].arguments_json == '{"query": "哈基镜"}'

gemini_client = FakeGeminiClient(
    ProviderConfig(
        id="fake-gemini",
        protocol="gemini",
        base_url="https://example.test/v1beta",
        api_key_env="GEMINI_API_KEY",
        default_model="gemini-test",
        models=["gemini-test"],
    ),
    {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "name": "get_identity",
                                "args": {"query": "哈基镜"},
                            }
                        }
                    ]
                },
            }
        ],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
    },
)
gemini_response = asyncio.run(gemini_client.complete(provider_request))
assert gemini_client.last_payload["tools"][0]["functionDeclarations"][0]["name"] == "get_identity"
assert gemini_response.tool_calls[0].name == "get_identity"
assert gemini_response.tool_calls[0].arguments_json == '{"query": "哈基镜"}'

# ── Streaming assembly tests ──

# OpenAI streaming: text only
openai_text_chunks = [
    {"model": "gpt-5.4", "choices": [{"delta": {"content": "你好"}, "finish_reason": None}]},
    {"model": "gpt-5.4", "choices": [{"delta": {"content": "世界"}, "finish_reason": None}]},
    {"model": "gpt-5.4", "choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}},
]
openai_stream_resp = OpenAIProviderClient._assemble_stream_response(openai_text_chunks, "gpt-5.4")
assert openai_stream_resp.text == "你好世界"
assert openai_stream_resp.finish_reason == "stop"
assert openai_stream_resp.input_tokens == 10
assert openai_stream_resp.output_tokens == 2
assert openai_stream_resp.tool_calls == []

# OpenAI streaming: tool calls with incremental arguments
openai_tool_chunks = [
    {"model": "gpt-5.4", "choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "search_web", "arguments": '{"qu'}}]}, "finish_reason": None}]},
    {"model": "gpt-5.4", "choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ery": "test"}'}}]}, "finish_reason": None}]},
    {"model": "gpt-5.4", "choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
]
openai_tool_resp = OpenAIProviderClient._assemble_stream_response(openai_tool_chunks, "gpt-5.4")
assert openai_tool_resp.text == ""
assert len(openai_tool_resp.tool_calls) == 1
assert openai_tool_resp.tool_calls[0].id == "call_1"
assert openai_tool_resp.tool_calls[0].name == "search_web"
assert json.loads(openai_tool_resp.tool_calls[0].arguments_json) == {"query": "test"}
assert openai_tool_resp.finish_reason == "tool_calls"

# OpenAI content sanitizing: leading reasoning tags/fences should not leak
assert strip_leading_reasoning_content("<think>\n先想一想\n</think>\n最终答复") == "最终答复"
assert strip_leading_reasoning_content("```thinking\n分析\n```\n最终答复") == "最终答复"

openai_reasoning_chunks = [
    {"model": "gpt-5.4", "choices": [{"delta": {"content": "<think>\n先想一想\n</think>\n"}, "finish_reason": None}]},
    {"model": "gpt-5.4", "choices": [{"delta": {"content": "最终答复"}, "finish_reason": "stop"}]},
]
openai_reasoning_resp = OpenAIProviderClient._assemble_stream_response(openai_reasoning_chunks, "gpt-5.4")
assert openai_reasoning_resp.text == "最终答复"

# Claude streaming: text only
claude_text_chunks = [
    {"_sse_event": "message_start", "message": {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 15}}},
    {"_sse_event": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"_sse_event": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "你好"}},
    {"_sse_event": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "世界"}},
    {"_sse_event": "content_block_stop", "index": 0},
    {"_sse_event": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 8}},
]
claude_stream_resp = ClaudeProviderClient._assemble_stream_response(claude_text_chunks, "claude-sonnet-4-6")
assert claude_stream_resp.text == "你好世界"
assert claude_stream_resp.finish_reason == "end_turn"
assert claude_stream_resp.input_tokens == 15
assert claude_stream_resp.output_tokens == 8
assert claude_stream_resp.tool_calls == []

# Claude streaming: tool use
claude_tool_chunks = [
    {"_sse_event": "message_start", "message": {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 20}}},
    {"_sse_event": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "search_web"}},
    {"_sse_event": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"quer'}},
    {"_sse_event": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": 'y": "test"}'}},
    {"_sse_event": "content_block_stop", "index": 0},
    {"_sse_event": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 12}},
]
claude_tool_resp = ClaudeProviderClient._assemble_stream_response(claude_tool_chunks, "claude-sonnet-4-6")
assert claude_tool_resp.text == ""
assert len(claude_tool_resp.tool_calls) == 1
assert claude_tool_resp.tool_calls[0].id == "toolu_1"
assert claude_tool_resp.tool_calls[0].name == "search_web"
assert json.loads(claude_tool_resp.tool_calls[0].arguments_json) == {"query": "test"}

# Gemini streaming: text only
gemini_text_chunks = [
    {"candidates": [{"content": {"parts": [{"text": "你好"}]}}]},
    {"candidates": [{"content": {"parts": [{"text": "世界"}]}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4}},
]
gemini_stream_resp = GeminiProviderClient._assemble_stream_response(gemini_text_chunks, "gemini-pro")
assert gemini_stream_resp.text == "你好世界"
assert gemini_stream_resp.finish_reason == "STOP"
assert gemini_stream_resp.input_tokens == 10
assert gemini_stream_resp.output_tokens == 4
assert gemini_stream_resp.tool_calls == []

# Gemini streaming: function call
gemini_tool_chunks = [
    {"candidates": [{"content": {"parts": [{"functionCall": {"name": "search_web", "args": {"query": "test"}}}]}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}},
]
gemini_tool_resp = GeminiProviderClient._assemble_stream_response(gemini_tool_chunks, "gemini-pro")
assert gemini_tool_resp.text == ""
assert len(gemini_tool_resp.tool_calls) == 1
assert gemini_tool_resp.tool_calls[0].name == "search_web"
assert json.loads(gemini_tool_resp.tool_calls[0].arguments_json) == {"query": "test"}

# Streaming fallback: when stream_enabled=True but _post_stream_sse fails with non-LLMProviderError
class FakeStreamFallbackClient(OpenAIProviderClient):
    def __init__(self, config, response_data):
        super().__init__(config)
        self.response_data = response_data
        self.stream_attempted = False

    async def _prepare_image_inputs(self, image_urls):
        return []

    def _get_api_key(self) -> str:
        return "test-key"

    async def _post_stream_sse(self, url, headers, payload):
        self.stream_attempted = True
        raise ValueError("simulated stream parse failure")

    async def _post_json(self, url, headers, payload):
        return self.response_data

stream_fallback_config = ProviderConfig(
    id="test", protocol="openai", base_url="http://test",
    api_key_env="TEST_KEY", default_model="gpt-test", models=["gpt-test"],
    stream_enabled=True,
)
stream_fallback_client = FakeStreamFallbackClient(
    stream_fallback_config,
    {"choices": [{"message": {"content": "fallback reply"}, "finish_reason": "stop"}], "model": "gpt-test"},
)
stream_fallback_resp = asyncio.run(stream_fallback_client.complete(provider_request))
assert stream_fallback_client.stream_attempted
assert stream_fallback_resp.text == "fallback reply"


class StubReasoningLeakProviderClient:
    async def complete(self, request):
        return LLMResponse(
            text="<think>\n内部分析\n</think>\n\n给群友看的答案",
            model=request.model,
            finish_reason="stop",
        )


llm_runtime_module.build_provider_client = lambda provider: StubReasoningLeakProviderClient()
try:
    reasoning_sanitized_result = asyncio.run(
        service.generate_reply(
            group_id=1003,
            user_id=3004,
            sender_name="测试用户",
            prompt="解释一下",
            recent_messages=[],
        )
    )
finally:
    llm_runtime_module.build_provider_client = original_builder

assert reasoning_sanitized_result["reply"] == "给群友看的答案"

print("LLM 测试通过")
