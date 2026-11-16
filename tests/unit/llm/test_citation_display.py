"""Citation projection protects facts, operational links and original coordinates."""
from copy import deepcopy

import pytest

from quickquip.llm.citation_display import project_citations
from quickquip.llm.provider.base import LLMResponse, LLMWebSearchReport, LLMWebSearchSource
from quickquip.llm.provider.gemini import GeminiProviderClient
from quickquip.llm.provider.openai_responses.response import parse_responses_body
from quickquip.llm.reply_presentation import prepare_reply


def response_with_citation(text, fragment, *, url="https://docs.example/policy", title="来源"):
    start = text.index(fragment)
    body = {"status": "completed", "output": [{
        "type": "message", "role": "assistant", "content": [{
            "type": "output_text", "text": text,
            "annotations": [{"type": "url_citation", "url": url, "title": title,
                             "start_index": start, "end_index": start + len(fragment)}],
        }],
    }]}
    original = deepcopy(body)
    response = parse_responses_body(body, provider_id="test", fallback_model="model")
    assert body == original
    assert response.native_blocks == original["output"]
    return response


@pytest.mark.parametrize("fragment", [
    "([docs.example](https://docs.example/policy))",
    "（[docs.example](https://docs.example/policy)）",
    "\ue200cite\ue202turn0search0\ue201",
])
def test_confirmed_citations_hide_scaffolding_and_keep_fact(fragment):
    response = response_with_citation("事实已核实。" + fragment + "接下来操作。", fragment)
    saved = response.text
    prepared = prepare_reply(response)
    assert prepared.display.text == "事实已核实。接下来操作。"
    assert response.text == saved
    assert "https://docs.example/policy" in prepared.text


def test_annotation_over_fact_removes_only_added_url_not_the_fact():
    response = response_with_citation("3.14 是结果。", "3.14 是结果。")
    prepared = prepare_reply(response)
    assert prepared.display.text == "3.14 是结果。"
    assert prepared.text.startswith("3.14 是结果。")


@pytest.mark.parametrize(("text", "expected"), [
    ("根据 https://docs.example/policy。后文事实不能丢。", "根据 。后文事实不能丢。"),
    ("结果 (https://docs.example/policy)；附加事实。", "结果 ；附加事实。"),
    ("事实（[docs.example](https://docs.example/policy)）。", "事实。"),
])
def test_sentence_annotation_keeps_text_after_url_and_balanced_wrappers(text, expected):
    assert project_citations(text, [(0, len(text))]).text == expected


def test_sentence_with_inline_code_still_hides_its_external_citation():
    response = response_with_citation("请使用 `foo()` 参数。", "请使用 `foo()` 参数。")
    assert prepare_reply(response).display.text == "请使用 `foo()` 参数。"
    code = "代码 `https://literal.example/` 正文 (https://reference.example/)"
    assert project_citations(code, [(0, len(code))]).text == "代码 `https://literal.example/` 正文"


@pytest.mark.parametrize("fact", ["3.14", "1.2.3", "sqlite3.connect", "example.com", "2026"])
def test_plain_annotation_cannot_turn_a_scalar_fact_into_a_source_label(fact):
    response = response_with_citation(fact, fact)
    assert prepare_reply(response).display.text == fact


def test_cleanup_and_multiple_parts_keep_citation_coordinates():
    first = response_with_citation(
        " <think>私有推理</think>\n\n\n甲😀([docs.example](https://docs.example/policy))乙 ",
        "([docs.example](https://docs.example/policy))",
    ).native_blocks[0]
    second = deepcopy(first)
    second["content"][0] = {"type": "output_text", "text": "丙[1](https://b.example/a_(b))丁",
                             "annotations": []}
    response = parse_responses_body({"status": "completed", "output": [first, second]},
                                    provider_id="test", fallback_model="model")
    prepared = prepare_reply(response)
    assert prepared.display.text == "甲😀乙 丙丁"
    assert "私有推理" not in prepared.text
    assert "https://docs.example/policy" in prepared.text


def test_functional_links_code_and_source_word_are_preserved():
    text = (
        "去 [控制台](https://console.example/) 操作，下载 https://files.example/a.zip。\n"
        "来源：\n这是来源系统的说明。\n"
        "```md\n来源：\n- [编号](https://code.example/)\n```\n"
        "示例 `[1](https://inline.example/)`。"
    )
    assert project_citations(text).text == text


def test_source_list_and_numbered_references_only_hide_display():
    text = ("事实。[1](https://a.example/x_(y))\n\n来源：\n"
            "- [完整标题](https://a.example/x)\n- https://b.example/\n"
            "\n继续说明与 [下载](https://files.example/) 。")
    projection = project_citations(text)
    assert "事实。" in projection.text
    assert "完整标题" not in projection.text
    assert "https://a.example" not in projection.text
    assert "https://files.example/" in projection.text
    assert "".join(text[i] for i in projection.positions) == projection.text
    assert projection.boundary(0) == 0
    assert projection.boundary(len(projection.text)) == len(text)


@pytest.mark.parametrize("header", ["来源：", "**来源：**", "### 来源", "**Sources**:"])
@pytest.mark.parametrize("entry", ["[官方文档](https://docs.example/x)",
                                    "官方文档 (https://docs.example/x)"])
def test_source_list_heading_styles_and_plain_title_links(header, entry):
    text = f"结论。\n\n{header}\n- {entry}"
    assert project_citations(text).text == "结论。"


def test_bad_offsets_and_invalid_url_are_not_a_rendering_failure():
    raw = "事实。[域名](http://[invalid/path)"
    response = LLMResponse(text=raw, model="test", citation_spans=[(True, 1000), (-1, 20)])
    assert prepare_reply(response).display.text == raw


def test_gemini_source_metadata_survives_without_changing_parts():
    parts = [{"text": "有来源的事实。", "thoughtSignature": "signed-original"}]
    grounding = {"webSearchQueries": ["事实"], "groundingChunks": [{"web": {
        "uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/opaque",
        "title": "原站点",
    }}], "groundingSupports": [{"segment": {"endIndex": 24}, "groundingChunkIndices": [0]}]}
    response = GeminiProviderClient._parse_candidate(
        {"content": {"parts": deepcopy(parts)}, "groundingMetadata": deepcopy(grounding)}, "test",
    )
    prepared = prepare_reply(response)
    assert prepared.display.text == "有来源的事实。"
    assert response.native_blocks == parts
    assert prepared.presentation["search"]["raw_metadata"] == grounding
    assert prepared.presentation["search"]["sources"][0]["url"].endswith("/opaque")


def test_known_source_url_used_as_action_link_is_not_deleted():
    text = "请到 [控制台](https://console.example/) 创建项目。"
    response = LLMResponse(text=text, model="test", web_search=LLMWebSearchReport(
        sources=[LLMWebSearchSource(title="控制台", url="https://console.example/")],
    ))
    assert prepare_reply(response).display.text == text
