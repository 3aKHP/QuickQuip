"""Skill 系统集成测试（PR-C 验收映射 §四 的三行 + C2 热部署）。

- 全链闭环：脚本化 provider 驱动 激活 → 检索 → 读资源 → 跑脚本 → 最终回答；
  逐轮请求满足尾部 append-only（前缀缓存/回放安全契约，D8）。
- 默认零影响（C2）：空 catalog 目录与 ``enabled = false`` 的请求序列化逐字节
  一致；非空目录的 catalog 块挂系统提示静态段末尾、同目录重扫字节稳定。
- 合规接缝（D6）：skill 工具产出与 search_web 结果同门槛过敏感词扫描
  （tool_result_pipeline 统一接缝：长文标记 scrub、短文/多命中整段丢弃）。
- 热部署（D3）：首轮空目录 → 放入 skill → 次轮 catalog 块出现且工具经惰性
  注册进入执行面（spec 广告滞后一轮的接缝行为见测试内标注）。

预置资产照单测先例复制 skills.example/ 到临时目录（忽略 __pycache__），
保持目录扫描与 SHA-256 复验的确定性。
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from plugins.llm_runtime import LLMService
from plugins.web_search import SearchResponse, SearchResult

import quickquip.llm.service_parts.tools as llm_tools_module
from quickquip.common.sensitive_filter import SCRUB_PLACEHOLDER
from quickquip.llm.provider import LLMRequest, LLMResponse
from quickquip.llm.tools import LLMConversationMessage, LLMToolCall
from tests.fixtures.configs import MIN_LLM_CONFIG_TOML, write_llm_config_bundle
from tests.fixtures.sensitive_filter import make_sensitive_filter
from tests.unit.llm.skills.conftest import write_skill

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_EXAMPLE_DIR = REPO_ROOT / "skills.example"

SKILL_TOOL_NAMES = (
    "activate_skill",
    "read_skill_resource",
    "search_skill_resources",
    "run_skill_script",
)

_TOOL_RESULT_BLOCK_REPLACEMENT = (
    "工具返回内容包含违规内容，已整体丢弃。请尝试其他查询、来源或换个表述。"
)

_CLOCK_LINE = re.compile(r"- 当前时间：[^\n]*（北京时间）")


class ScriptedSkillClient:
    """按剧本回放工具调用链的 stub provider client。

    ``script`` 中每个元素是一轮要声明的工具调用；剧本耗尽后返回
    ``final_text`` 作为最终回答。``requests`` 记录每次实际请求供断言。
    """

    def __init__(self, script: list[list[LLMToolCall]], final_text: str) -> None:
        self._script = list(script)
        self._final_text = final_text
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        round_index = len(self.requests) - 1
        assert round_index <= len(self._script), (
            f"剧本耗尽：第 {round_index + 1} 次请求不应出现"
        )
        if round_index < len(self._script):
            return LLMResponse(
                text="",
                model=request.model,
                tool_calls=self._script[round_index],
                finish_reason="tool_calls",
            )
        return LLMResponse(text=self._final_text, model=request.model, finish_reason="stop")


def _service(base_dir: Path, *, tool_max_rounds: int = 2, skills_toml: str = "") -> LLMService:
    base_dir.mkdir(parents=True, exist_ok=True)
    config_toml = MIN_LLM_CONFIG_TOML.replace(
        "tool_max_rounds = 2", f"tool_max_rounds = {tool_max_rounds}"
    )
    if skills_toml:
        config_toml = f"{config_toml}\n{skills_toml}"
    bundle = write_llm_config_bundle(base_dir, config_toml=config_toml)
    return LLMService(**bundle)


def _catalog_toml(catalog_dir: Path) -> str:
    return f'[skills]\ncatalog_dir = "{catalog_dir}"\n'


def _copy_bundled_skills(catalog_dir: Path) -> None:
    for name in ("self-docs", "host-healthcheck"):
        shutil.copytree(
            SKILLS_EXAMPLE_DIR / name,
            catalog_dir / name,
            ignore=shutil.ignore_patterns("__pycache__"),
        )


def _message_fingerprint(message: LLMConversationMessage) -> tuple:
    return (
        message.role,
        message.content,
        message.tool_call_id,
        message.tool_name,
        message.is_tool_error,
        tuple((call.id, call.name, call.arguments_json) for call in message.tool_calls),
    )


def _normalized_request_fingerprint(request: LLMRequest) -> tuple:
    """请求序列化指纹；信封时钟行是唯一逐轮变化字段，归一化后参与字节比较。"""
    messages = tuple(
        (
            message.role,
            _CLOCK_LINE.sub("- 当前时间：<NOW>", message.content),
            message.tool_call_id,
            message.tool_name,
            message.is_tool_error,
            tuple((call.id, call.name, call.arguments_json) for call in message.tool_calls),
        )
        for message in request.messages
    )
    return (
        request.model,
        request.system_prompt,
        request.temperature,
        request.max_output_tokens,
        request.thinking_budget,
        request.allow_tool_calls,
        request.tool_choice,
        request.builtin_search,
        tuple(
            (spec.name, spec.description, json.dumps(spec.input_schema, sort_keys=True))
            for spec in request.tools
        ),
        messages,
    )


def _spec_names(request: LLMRequest) -> list[str]:
    return [spec.name for spec in request.tools]


def _tool_messages(request: LLMRequest) -> list[LLMConversationMessage]:
    return [message for message in request.messages if message.role == "tool"]


# ── 全链闭环：激活 → 检索 → 读资源 → 跑脚本 → 最终回答 ─────────────────────


async def test_skill_full_chain_append_only(tmp_path, patch_provider_builder):
    catalog_dir = tmp_path / "skills"
    _copy_bundled_skills(catalog_dir)
    service = _service(
        tmp_path / "svc", tool_max_rounds=8, skills_toml=_catalog_toml(catalog_dir)
    )
    client = ScriptedSkillClient(
        script=[
            [LLMToolCall("call_activate_docs", "activate_skill", '{"name":"self-docs"}')],
            [
                LLMToolCall(
                    "call_search",
                    "search_skill_resources",
                    '{"skill":"self-docs","query":"/quote search"}',
                )
            ],
            [
                LLMToolCall(
                    "call_read",
                    "read_skill_resource",
                    '{"skill":"self-docs",'
                    '"path":"references/docs-user-group-commands.md",'
                    '"start_line":1,"end_line":5}',
                )
            ],
            [
                LLMToolCall(
                    "call_activate_health", "activate_skill", '{"name":"host-healthcheck"}'
                )
            ],
            [
                LLMToolCall(
                    "call_run",
                    "run_skill_script",
                    '{"skill":"host-healthcheck","path":"scripts/collect.py"}',
                )
            ],
        ],
        final_text="语录搜索用法见群命令文档；宿主机负载正常（host-proc 视图）。",
    )
    patch_provider_builder(lambda provider: client)

    result = await service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="/quote search 怎么用？顺便看看服务器状态。",
        recent_messages=[],
        trigger_auto_memory=False,
    )

    # 五轮工具调用 + 最终回答，共六次请求。
    assert len(client.requests) == 6
    assert result["reply"] == "语录搜索用法见群命令文档；宿主机负载正常（host-proc 视图）。"

    # 尾部 append-only：每一轮请求的消息序列都是下一轮请求的逐字节前缀。
    for previous, current in zip(client.requests, client.requests[1:]):
        previous_fp = [_message_fingerprint(message) for message in previous.messages]
        current_fp = [_message_fingerprint(message) for message in current.messages]
        assert len(current_fp) > len(previous_fp)
        assert current_fp[: len(previous_fp)] == previous_fp

    # 工具结果按声明序落在会话尾部：激活→检索→读→激活→跑脚本。
    tool_messages = _tool_messages(client.requests[-1])
    assert [message.tool_name for message in tool_messages] == [
        "activate_skill",
        "search_skill_resources",
        "read_skill_resource",
        "activate_skill",
        "run_skill_script",
    ]
    assert all(not message.is_tool_error for message in tool_messages)

    # 1) activate_skill(self-docs)：标记 + 正文注入。
    activation_docs = tool_messages[0].content
    assert '[skill_activation name="self-docs" hash="' in activation_docs
    assert 'status="activated"' in activation_docs
    assert "# QuickQuip 文档问答" in activation_docs
    assert "[/skill_activation]" in activation_docs

    # 2) search_skill_resources：关键词型问题命中正确 reference（file:line + 上下文）。
    search_result = tool_messages[1].content
    assert '[skill_search name="self-docs" query="/quote search" matches=' in search_result
    assert "references/docs-user-group-commands.md:" in search_result

    # 3) read_skill_resource：按行区间读取，带行段标注与资源标记。
    read_result = tool_messages[2].content
    assert (
        '[skill_resource name="self-docs" '
        'path="references/docs-user-group-commands.md"]'
    ) in read_result
    assert "Generated from docs/user/group-commands.md" in read_result
    assert re.search(r"\[第 1-5 行，共 \d+ 行\]", read_result)

    # 4) activate_skill(host-healthcheck)：第二个 skill 独立激活。
    activation_health = tool_messages[3].content
    assert '[skill_activation name="host-healthcheck" hash="' in activation_health
    assert "# host-healthcheck 宿主机健康检查" in activation_health

    # 5) run_skill_script：collect.py 真实执行，JSON 输出含视图标注。
    script_result = tool_messages[4].content
    assert '[skill_script name="host-healthcheck" path="scripts/collect.py"' in script_result
    assert "退出码：0" in script_result
    stdout_json = script_result.split("stdout:\n", 1)[1].split("\n\nstderr:", 1)[0]
    report = json.loads(stdout_json)
    assert report["schema"] == "quickquip.host-healthcheck/1"
    assert report["levels"]["L0"] is True
    assert {"host-proc", "cgroup", "host-metrics-file", "host-mount"} <= set(report["views"])
    assert all("view" in group for group in report["groups"].values())

    # per-会话激活登记表（D5）：两个 skill 均已激活。
    assert service._skill_activations.activated_names("1001") == [
        "host-healthcheck",
        "self-docs",
    ]

    # catalog 块在系统提示静态段末尾，activate 的 name enum 即目录名单。
    system_prompt = client.requests[0].system_prompt
    assert system_prompt.endswith("</skill_catalog>")
    (activate_spec,) = [
        spec for spec in client.requests[0].tools if spec.name == "activate_skill"
    ]
    assert activate_spec.input_schema["properties"]["name"]["enum"] == [
        "host-healthcheck",
        "self-docs",
    ]


# ── 默认零影响（C2）：空目录 ≡ 禁用基线，逐字节一致 ────────────────────────


async def test_empty_catalog_byte_identical_to_disabled_baseline(
    tmp_path, patch_provider_builder
):
    empty_catalog = tmp_path / "empty-skills"
    empty_catalog.mkdir()
    service_disabled = _service(tmp_path / "a", skills_toml="[skills]\nenabled = false\n")
    service_empty = _service(tmp_path / "b", skills_toml=_catalog_toml(empty_catalog))

    client_disabled = ScriptedSkillClient(script=[], final_text="基线回答。")
    patch_provider_builder(lambda provider: client_disabled)
    await service_disabled.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="介绍一下你自己。",
        recent_messages=[],
        trigger_auto_memory=False,
    )

    client_empty = ScriptedSkillClient(script=[], final_text="基线回答。")
    patch_provider_builder(lambda provider: client_empty)
    await service_empty.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="介绍一下你自己。",
        recent_messages=[],
        trigger_auto_memory=False,
    )

    # 空目录短路：工具不注册、catalog 块不渲染（C2 零可见即零扰动）。
    for name in SKILL_TOOL_NAMES:
        assert not service_empty.tool_registry.has_tool(name)

    request_disabled = client_disabled.requests[0]
    request_empty = client_empty.requests[0]
    assert "<skill_catalog" not in request_empty.system_prompt
    for name in SKILL_TOOL_NAMES:
        assert name not in _spec_names(request_empty)
    # 请求序列化逐项逐字节一致（系统提示、tool specs、消息、采样参数）。
    assert _normalized_request_fingerprint(request_empty) == _normalized_request_fingerprint(
        request_disabled
    )


async def test_catalog_block_static_tail_and_rescan_byte_stable(
    tmp_path, patch_provider_builder
):
    catalog_dir = tmp_path / "skills"
    _copy_bundled_skills(catalog_dir)
    service = _service(tmp_path / "svc", skills_toml=_catalog_toml(catalog_dir))
    client = ScriptedSkillClient(script=[], final_text="好的。")
    patch_provider_builder(lambda provider: client)

    for _ in range(2):
        await service.generate_reply(
            group_id=1001,
            user_id=2002,
            sender_name="测试用户",
            prompt="你好。",
            recent_messages=[],
            trigger_auto_memory=False,
        )

    assert len(client.requests) == 2
    first_prompt = client.requests[0].system_prompt
    second_prompt = client.requests[1].system_prompt
    # 同目录重扫字节稳定（前缀缓存契约）。
    assert first_prompt == second_prompt
    # catalog 块挂系统提示静态段末尾，按 name 字典序渲染。
    assert first_prompt.endswith("</skill_catalog>")
    assert first_prompt.index("- host-healthcheck:") < first_prompt.index("- self-docs:")
    spec_names = _spec_names(client.requests[0])
    for name in SKILL_TOOL_NAMES:
        assert name in spec_names
    (activate_spec,) = [
        spec for spec in client.requests[0].tools if spec.name == "activate_skill"
    ]
    assert activate_spec.input_schema["properties"]["name"]["enum"] == [
        "host-healthcheck",
        "self-docs",
    ]


# ── 合规接缝：skill 工具产出与 search_web 同门槛扫描 ───────────────────────


def _patch_pipeline_filter(monkeypatch, tmp_path) -> None:
    sensitive = make_sensitive_filter(tmp_path, "block")
    monkeypatch.setattr(
        "quickquip.llm.tool_result_pipeline._get_sensitive_filter", lambda: sensitive
    )


def _assert_scrubbed(message: LLMConversationMessage, *, preserved_marker: str) -> None:
    """长文单命中：标记 scrub（占位符替换、骨架保留），与 search_web 同门槛。

    scrub 产物取归一化形态（casefold、空格剔除），骨架标记按同一口径断言。
    """
    assert message.is_tool_error
    assert SCRUB_PLACEHOLDER in message.content
    assert "blocked" not in message.content
    normalized_marker = preserved_marker.casefold().replace(" ", "").replace("\t", "")
    assert normalized_marker in message.content


class _BlockedSearchClient:
    async def search(self, query, *, topic="general", max_results=5):
        return SearchResponse(
            query=query,
            answer="摘要里混入 blocked 一词。",
            results=[
                SearchResult(
                    title="示例页面",
                    url="https://example.test/page",
                    content="这是一段用于填充长度的安全文本。" * 20,
                )
            ],
        )


async def test_search_web_blocked_result_scrubbed_baseline(
    tmp_path, monkeypatch, patch_provider_builder
):
    """参照系：search_web 结果含敏感词 → 长文 scrub 标记（既有接缝行为）。"""
    empty_catalog = tmp_path / "empty-skills"
    empty_catalog.mkdir()
    service = _service(tmp_path / "svc", skills_toml=_catalog_toml(empty_catalog))
    _patch_pipeline_filter(monkeypatch, tmp_path)
    monkeypatch.setattr(
        llm_tools_module, "SearXNGSearchClient", lambda *args, **kwargs: _BlockedSearchClient()
    )
    client = ScriptedSkillClient(
        script=[[LLMToolCall("call_search", "search_web", '{"query":"填充"}')]],
        final_text="检索完成。",
    )
    patch_provider_builder(lambda provider: client)

    result = await service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="查一下填充资料。",
        recent_messages=[],
        trigger_auto_memory=False,
    )

    (search_message,) = _tool_messages(client.requests[-1])
    _assert_scrubbed(search_message, preserved_marker="联网搜索：")
    assert result["reply"] == "检索完成。"


async def test_skill_resource_blocked_content_scrubbed_same_gate(
    tmp_path, monkeypatch, patch_provider_builder
):
    """skill 资源产出与 search_web 同门槛：长文单命中 → 标记 scrub，Loop 继续。"""
    catalog_dir = tmp_path / "skills"
    write_skill(
        catalog_dir,
        "demo",
        "合规测试 skill。",
        body="合规测试正文。\n",
        files={
            "references/notes.md": (
                "这是一段用于填充长度的安全文本。\n" * 20 + "含 blocked 一词。\n"
            )
        },
    )
    service = _service(tmp_path / "svc", skills_toml=_catalog_toml(catalog_dir))
    _patch_pipeline_filter(monkeypatch, tmp_path)
    client = ScriptedSkillClient(
        script=[
            [LLMToolCall("call_activate", "activate_skill", '{"name":"demo"}')],
            [
                LLMToolCall(
                    "call_read",
                    "read_skill_resource",
                    '{"skill":"demo","path":"references/notes.md"}',
                )
            ],
        ],
        final_text="读取完成。",
    )
    patch_provider_builder(lambda provider: client)

    result = await service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="读一下 demo 的参考资料。",
        recent_messages=[],
        trigger_auto_memory=False,
    )

    tool_messages = _tool_messages(client.requests[-1])
    assert [message.tool_name for message in tool_messages] == [
        "activate_skill",
        "read_skill_resource",
    ]
    # 激活正文无命中，原样放行（逐结果粒度）。
    assert not tool_messages[0].is_tool_error
    assert "合规测试正文。" in tool_messages[0].content
    # 资源内容含敏感词：与 search_web 同一 scrub 门槛。
    _assert_scrubbed(
        tool_messages[1],
        preserved_marker='[skill_resource name="demo" path="references/notes.md"]',
    )
    assert result["reply"] == "读取完成。"


async def test_skill_script_blocked_stdout_replaced_wholesale(
    tmp_path, monkeypatch, patch_provider_builder
):
    """脚本 stdout 含敏感词且结果短小 → 同管道整段丢弃形态（拦截）。"""
    catalog_dir = tmp_path / "skills"
    write_skill(
        catalog_dir,
        "emit-demo",
        "脚本合规测试 skill。",
        body="脚本合规测试正文。\n",
        files={"scripts/emit.py": "print('blocked')\n"},
    )
    service = _service(tmp_path / "svc", skills_toml=_catalog_toml(catalog_dir))
    _patch_pipeline_filter(monkeypatch, tmp_path)
    client = ScriptedSkillClient(
        script=[
            [LLMToolCall("call_activate", "activate_skill", '{"name":"emit-demo"}')],
            [
                LLMToolCall(
                    "call_run",
                    "run_skill_script",
                    '{"skill":"emit-demo","path":"scripts/emit.py"}',
                )
            ],
        ],
        final_text="脚本输出已被安全过滤。",
    )
    patch_provider_builder(lambda provider: client)

    result = await service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="跑一下 emit-demo 的脚本。",
        recent_messages=[],
        trigger_auto_memory=False,
    )

    tool_messages = _tool_messages(client.requests[-1])
    assert [message.tool_name for message in tool_messages] == [
        "activate_skill",
        "run_skill_script",
    ]
    assert not tool_messages[0].is_tool_error
    run_message = tool_messages[1]
    assert run_message.is_tool_error
    assert run_message.content == _TOOL_RESULT_BLOCK_REPLACEMENT
    assert "blocked" not in run_message.content
    assert result["reply"] == "脚本输出已被安全过滤。"


# ── 热部署：空目录 → 放入 skill → 惰性注册生效 ─────────────────────────────


async def test_hot_deploy_lazy_registration(tmp_path, patch_provider_builder):
    catalog_dir = tmp_path / "skills"
    catalog_dir.mkdir()
    service = _service(tmp_path / "svc", skills_toml=_catalog_toml(catalog_dir))

    # 首轮空目录：无 skill 工具、无 catalog 块。
    first = ScriptedSkillClient(script=[], final_text="首轮回答。")
    patch_provider_builder(lambda provider: first)
    await service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="你好。",
        recent_messages=[],
        trigger_auto_memory=False,
    )
    first_request = first.requests[0]
    assert "<skill_catalog" not in first_request.system_prompt
    for name in SKILL_TOOL_NAMES:
        assert name not in _spec_names(first_request)
        assert not service.tool_registry.has_tool(name)

    # 运行中放入 skill，无 reload 钩子。
    write_skill(catalog_dir, "late-demo", "热部署演示 skill。", body="热部署正文内容。\n")

    second = ScriptedSkillClient(
        script=[[LLMToolCall("call_activate", "activate_skill", '{"name":"late-demo"}')]],
        final_text="次轮回答。",
    )
    patch_provider_builder(lambda provider: second)
    result = await service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="激活刚部署的 skill。",
        recent_messages=[],
        trigger_auto_memory=False,
    )

    # 次轮：catalog 块出现在系统提示静态段末尾，工具经惰性注册进入注册表，
    # 当轮即可被执行路径调用（registry.execute 不校验 spec 广告）。
    second_request = second.requests[0]
    assert second_request.system_prompt.endswith("</skill_catalog>")
    assert "- late-demo: 热部署演示 skill。" in second_request.system_prompt
    for name in SKILL_TOOL_NAMES:
        assert service.tool_registry.has_tool(name)
    # 已知接缝行为（已上报）：tool specs 在 _skills_catalog_block 惰性注册之前
    # 计算（service.py 调用序），spec 广告滞后一轮，第三轮起进入广告面。
    for name in SKILL_TOOL_NAMES:
        assert name not in _spec_names(second_request)
    (activation_message,) = _tool_messages(second.requests[-1])
    assert not activation_message.is_tool_error
    assert '[skill_activation name="late-demo" hash="' in activation_message.content
    assert 'status="activated"' in activation_message.content
    assert "热部署正文内容。" in activation_message.content
    assert result["reply"] == "次轮回答。"

    # 第三轮：4 个工具进入广告 specs，activate 的 name enum 即当前名单。
    third = ScriptedSkillClient(script=[], final_text="第三轮回答。")
    patch_provider_builder(lambda provider: third)
    await service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="再说一次。",
        recent_messages=[],
        trigger_auto_memory=False,
    )
    spec_names = _spec_names(third.requests[0])
    for name in SKILL_TOOL_NAMES:
        assert name in spec_names
    (activate_spec,) = [
        spec for spec in third.requests[0].tools if spec.name == "activate_skill"
    ]
    assert activate_spec.input_schema["properties"]["name"]["enum"] == ["late-demo"]
