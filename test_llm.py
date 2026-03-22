import asyncio
import textwrap
from pathlib import Path
import shutil

import plugins.llm_runtime as llm_runtime_module
from plugins.llm_inputs import extract_llm_input, extract_llm_prompt
from plugins.message_deduper import RecentMessageDeduper
from plugins.llm_provider import LLMResponse
from plugins.llm_runtime import LLMService, ResolvedGroupSettings
from plugins.recent_message_buffer import RecentMessageBuffer
from plugins.tavily_search import TavilySearchResponse, TavilySearchResult, format_search_response
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


class StubProviderClient:
    last_request = None

    async def complete(self, request):
        StubProviderClient.last_request = request
        return LLMResponse(
            text=f"stub::{request.model}::{request.prompt}",
            model=request.model,
            input_tokens=11,
            output_tokens=7,
        )


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

    [triggers]
    default_prefix = "/ai"
    allow_prefix = true
    allow_at = true
    empty_prompt_reply = "empty"

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

prefix_message = DummyMessage([DummySegment("text", {"text": "/ai 你好"})])
assert extract_llm_prompt(prefix_message, "12345", prefix_settings) == "你好"

mention_message = DummyMessage(
    [
        DummySegment("at", {"qq": "12345"}),
        DummySegment("text", {"text": " 讲个笑话"}),
    ]
)
assert extract_llm_prompt(mention_message, "12345", prefix_settings) == "讲个笑话"

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

non_trigger_message = DummyMessage([DummySegment("text", {"text": "普通消息"})])
assert extract_llm_prompt(non_trigger_message, "12345", prefix_settings) is None

recent_buffer = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
for index in range(25):
    recent_buffer.add_message(1, index, f"用户{index}", f"消息{index}", now_ts=index)
recent_items = recent_buffer.list_recent(1, now_ts=25)
assert len(recent_items) == 20
assert recent_items[0]["text"] == "消息5"
assert recent_items[-1]["text"] == "消息24"
assert recent_buffer.list_recent(1, now_ts=90) == []

deduper = RecentMessageDeduper(max_ids_per_group=2)
assert deduper.is_duplicate(1, 10001) is False
assert deduper.is_duplicate(1, 10001) is True
assert deduper.is_duplicate(1, 10002) is False
assert deduper.is_duplicate(1, 10003) is False
assert deduper.is_duplicate(1, 10001) is False

assert _is_self_message(DummyEvent(user_id=12345, self_id=12345)) is True
assert _is_self_message(DummyEvent(user_id=12345, self_id=54321)) is False

artifact_dir = Path("dev/sandbox/test_artifacts/llm_test")
if artifact_dir.exists():
    shutil.rmtree(artifact_dir)
artifact_dir.mkdir(parents=True, exist_ok=True)

config_path = artifact_dir / "llm.toml"
db_path = artifact_dir / "llm.db"
vocab_path = artifact_dir / "vocab.yaml"
config_path.write_text(CONFIG_TEXT, encoding="utf-8")
vocab_path.write_text(VOCAB_TEXT, encoding="utf-8")

service = LLMService(config_path=config_path, db_path=db_path, vocab_path=vocab_path)
assert service.config.load_error is None
assert service.format_status(1001).startswith("LLM 状态")

service.set_group_model(1001, "openai-main", "gpt-alt")
service.set_group_persona(1001, "default")
service.set_group_trigger_prefix(1001, "/bot")
service.set_group_allow_at(1001, False)
service.set_group_allow_prefix(1001, True)

status = service.format_status(1001)
assert "Model：gpt-alt" in status
assert "(/bot)" in status
assert "艾特触发：OFF" in status
assert "临时上下文：触发前最多 20 条群消息" in status
assert "记忆注入：ON" in status

current = service.format_current(1001)
assert current.startswith("LLM 当前配置")
assert "短期会话：已存 0 条" in current
assert "长期记忆：已存 0 条" in current

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
                {"user_id": "u1", "sender_name": "甲", "text": "昨晚排位真红温。"},
                {"user_id": "u2", "sender_name": "乙", "text": "哈基镜今天又在发病。"},
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
assert "哈基镜 通常指 镜子" in StubProviderClient.last_request.system_prompt
assert "不要和王者荣耀的镜混淆" in StubProviderClient.last_request.system_prompt
assert "区：群里常见的内部称谓" in StubProviderClient.last_request.system_prompt
assert StubProviderClient.last_request.history_messages[0]["content"].startswith("以下是本次触发前")
assert "甲：昨晚排位真红温。" in StubProviderClient.last_request.history_messages[0]["content"]
assert "乙：哈基镜今天又在发病。" in StubProviderClient.last_request.history_messages[0]["content"]
assert StubProviderClient.last_request.image_urls == []
assert all(
    item["content"] != "哈基镜是区吗？"
    for item in StubProviderClient.last_request.history_messages
)

history = service.store.list_recent_conversation_messages(1001, 10)
assert history[-2]["role"] == "user"
assert history[-2]["content"] == "哈基镜是区吗？"
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

original_builder = llm_runtime_module.build_provider_client
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
assert StubProviderClient.last_request.image_urls == ["https://example.test/cat.png"]
assert StubProviderClient.last_request.prompt.startswith("请描述这张图片")

print("LLM 测试通过")
