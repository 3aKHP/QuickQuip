from __future__ import annotations

import json
from pathlib import Path

import pytest

from quickquip.chat.group_quotes import GroupQuoteStore
from quickquip.common.identity import IdentityIndex
from quickquip.common.identity_sources import IdentitySnapshot
from quickquip.llm.quote_tools import (
    QUERY_GROUP_QUOTES_TOOL_NAME,
    QUOTE_LOOP_BUDGET_TOKENS,
    QuoteToolDeps,
    redact_quote_arguments,
    run_group_quote_query,
)
from quickquip.llm.service import LLMService
from quickquip.llm.tools import LLMToolCall, ToolExecutionContext
from tests.fixtures.configs import write_llm_config_bundle


def _ctx(*, group_id: int | str = 1001, chat_type: str = "group") -> ToolExecutionContext:
    return ToolExecutionContext(
        group_id=group_id,
        user_id="1000000001",
        sender_name="测试员",
        provider_id="fake",
        model="fake-model",
        chat_type=chat_type,
    )


def _deps(
    store: GroupQuoteStore | None,
    *,
    user_names: dict[str, str] | None = None,
    candidates_map: dict[str, list[str]] | None = None,
) -> QuoteToolDeps:
    names = user_names or {}
    snap = IdentitySnapshot(names=names, index=IdentityIndex())
    cmap = candidates_map or {}
    return QuoteToolDeps(
        quote_store=store,
        resolve_speaker=lambda gid, q: list(cmap.get(q, [])),
        get_identity_snapshot=lambda gid: snap,
    )


@pytest.mark.asyncio
async def test_private_chat_and_unbound_store_handling(tmp_path: Path):
    store = GroupQuoteStore(tmp_path / "quotes.db")
    private_res = await run_group_quote_query({}, _ctx(chat_type="private"), _deps(store))
    assert "仅支持群聊" in private_res.content
    assert private_res.is_error is False

    unbound_res = await run_group_quote_query({}, _ctx(), None)
    assert unbound_res.is_error is True
    assert "未接入" in unbound_res.content

    store._unavailable = True
    unavail_res = await run_group_quote_query({}, _ctx(), _deps(store))
    assert unavail_res.is_error is True
    assert "暂时不可用" in unavail_res.content


@pytest.mark.asyncio
async def test_seq_lookup_and_cross_group_isolation(tmp_path: Path):
    store = GroupQuoteStore(tmp_path / "quotes.db")
    store.add("1001", "123456", "旧昵称", "第一条群A金句", "1000000001")
    store.add("1002", "123456", "旧昵称", "群B私密语录", "1000000001")

    deps = _deps(store, user_names={"123456": "新昵称"})
    res = await run_group_quote_query({"seq": 1}, _ctx(group_id=1001), deps)
    assert res.is_error is False
    assert "#1" in res.content
    assert "第一条群A金句" in res.content
    assert "新昵称" in res.content
    assert "原名：旧昵称" in res.content
    assert "群B私密语录" not in res.content

    missing = await run_group_quote_query({"seq": 99}, _ctx(group_id=1001), deps)
    assert "不存在编号为 #99" in missing.content
    assert "共 1 条" in missing.content

    bad_seq = await run_group_quote_query({"seq": 0}, _ctx(group_id=1001), deps)
    assert "正整数" in bad_seq.content


@pytest.mark.asyncio
async def test_keyword_speaker_combined_filter_and_pagination(tmp_path: Path):
    store = GroupQuoteStore(tmp_path / "quotes.db")
    store.add("1001", "123456", "张三", "今天天气真好", "1000000001")
    store.add("1001", "123456", "张三", "写代码真开心", "1000000001")
    store.add("1001", "987654", "李四", "今天写代码也开心", "1000000001")

    deps = _deps(
        store,
        user_names={"123456": "张三", "987654": "李四"},
        candidates_map={"张三": ["123456"], "小名": ["123456", "987654"]},
    )

    # 关键词 + 发言人组合
    combined = await run_group_quote_query(
        {"keyword": "开心", "speaker": "张三"}, _ctx(group_id=1001), deps
    )
    assert "写代码真开心" in combined.content
    assert "李四" not in combined.content

    # 模糊发言人匹配到多个不同身份时提示消歧
    ambiguous = await run_group_quote_query({"speaker": "小名"}, _ctx(group_id=1001), deps)
    assert "匹配到多位群成员" in ambiguous.content
    assert "123456" in ambiguous.content and "987654" in ambiguous.content

    # 分页
    page1 = await run_group_quote_query({"limit": 2, "offset": 0}, _ctx(group_id=1001), deps)
    assert "共 3 条，本页显示 1–2" in page1.content
    assert "offset=2" in page1.content

    page2 = await run_group_quote_query({"limit": 2, "offset": 2}, _ctx(group_id=1001), deps)
    assert "共 3 条，本页显示 3–3" in page2.content
    assert "offset=" not in page2.content

    beyond = await run_group_quote_query({"limit": 2, "offset": 10}, _ctx(group_id=1001), deps)
    assert "已超出结果范围" in beyond.content


@pytest.mark.asyncio
async def test_empty_and_budget_exhausted_and_media_placeholder(tmp_path: Path):
    store = GroupQuoteStore(tmp_path / "quotes.db")
    deps = _deps(store)

    empty = await run_group_quote_query({}, _ctx(group_id=1001), deps)
    assert "暂无已收藏的语录" in empty.content

    store.add(
        "1001",
        "123456",
        "张三",
        "经典发言",
        "1000000001",
        content_parts={
            "version": 1,
            "parts": [{"type": "media", "media": "image"}, {"type": "text", "text": " 经典发言"}],
        },
    )
    no_match = await run_group_quote_query({"keyword": "不存在的词"}, _ctx(group_id=1001), deps)
    assert "没有匹配条件" in no_match.content

    ctx = _ctx(group_id=1001)
    media = await run_group_quote_query({"seq": 1}, ctx, deps)
    assert "[图片]" in media.content
    assert "CQ:image" not in media.content
    assert "-20" not in media.content and ":" in media.content
    assert ctx.quote_query_tokens_used > 0

    ctx.quote_query_tokens_used = QUOTE_LOOP_BUDGET_TOKENS
    exhausted = await run_group_quote_query({}, ctx, deps)
    assert "查询额度已用完" in exhausted.content


def test_redact_quote_arguments_drops_raw_keyword_and_speaker():
    redacted_filter = json.loads(
        redact_quote_arguments('{"keyword": "秘密词", "speaker": "张三", "limit": 5, "offset": 2}')
    )
    assert redacted_filter == {
        "has_keyword": True,
        "has_speaker": True,
        "limit": 5,
        "mode": "filter",
        "offset": 2,
    }
    assert "秘密词" not in json.dumps(redacted_filter, ensure_ascii=False)
    assert "张三" not in json.dumps(redacted_filter, ensure_ascii=False)

    redacted_seq = json.loads(redact_quote_arguments('{"seq": 7}'))
    assert redacted_seq == {"has_seq": True, "mode": "seq"}


@pytest.mark.asyncio
async def test_llm_service_registers_quote_tool_with_ephemeral_and_discovery(tmp_path: Path):
    paths = write_llm_config_bundle(tmp_path)
    service = LLMService(**paths)
    store = GroupQuoteStore(tmp_path / "quotes.db")
    store.add("1001", "123456", "张三", "测试服务集成语录", "1000000001")
    service.bind_group_quote_store(store)

    assert service.tool_registry.has_tool(QUERY_GROUP_QUOTES_TOOL_NAME)
    assert service.tool_registry.retention_of(QUERY_GROUP_QUOTES_TOOL_NAME) == "ephemeral"
    assert QUERY_GROUP_QUOTES_TOOL_NAME in service._get_enabled_tool_names(chat_type="group")
    assert QUERY_GROUP_QUOTES_TOOL_NAME not in service._get_enabled_tool_names(chat_type="private")

    # 按需发现可命中
    service.config.tools.discovery_mode = "on"
    assert QUERY_GROUP_QUOTES_TOOL_NAME in service._get_deferred_tool_names(chat_type="group")

    result = await service.tool_registry.execute(
        LLMToolCall(id="c1", name=QUERY_GROUP_QUOTES_TOOL_NAME, arguments_json='{"seq": 1}'),
        _ctx(group_id=1001),
    )
    assert result.is_error is False
    assert "测试服务集成语录" in result.content

    # 经真实 LLMService 走 speaker 路径（覆盖 _quote_deps -> snapshot.candidates）
    by_speaker = await service.tool_registry.execute(
        LLMToolCall(
            id="c2",
            name=QUERY_GROUP_QUOTES_TOOL_NAME,
            arguments_json='{"speaker": "张三", "keyword": "集成"}',
        ),
        _ctx(group_id=1001),
    )
    assert by_speaker.is_error is False
    assert "测试服务集成语录" in by_speaker.content

    # 验证参数脱敏走 registry 端到端链路
    redacted_call = service.tool_registry.redacted_declaration(
        LLMToolCall(
            id="c3",
            name=QUERY_GROUP_QUOTES_TOOL_NAME,
            arguments_json='{"speaker": "张三", "keyword": "秘密"}',
        )
    )
    assert "张三" not in redacted_call.arguments_json
    assert "秘密" not in redacted_call.arguments_json


@pytest.mark.asyncio
async def test_quote_tool_validation_truncation_and_seq_unavailable(tmp_path: Path):
    store = GroupQuoteStore(tmp_path / "quotes.db")
    for idx in range(1, 15):
        store.add("1001", "123456", "张三", f"超长语录第{idx}条：" + ("内容" * 120), "1000000001")
    deps = _deps(store)

    # 非法参数类型与超长输入
    bad_type = await run_group_quote_query({"seq": True}, _ctx(), deps)
    assert "必须是整数" in bad_type.content
    bad_kw = await run_group_quote_query({"keyword": "a" * 101}, _ctx(), deps)
    assert "关键词过长" in bad_kw.content

    # 页内 token 预算截断并给出正确的续查 offset
    ctx = _ctx()
    ctx.quote_query_tokens_used = QUOTE_LOOP_BUDGET_TOKENS - 300
    truncated = await run_group_quote_query({"limit": 10}, ctx, deps)
    assert "本页因长度预算截断" in truncated.content
    assert "offset=" in truncated.content

    # seq 分支遇到数据库不可用返回 is_error=True
    store._unavailable = True
    unavail = await run_group_quote_query({"seq": 1}, _ctx(), deps)
    assert unavail.is_error is True
    assert "暂时不可用" in unavail.content
