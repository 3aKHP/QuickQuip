from __future__ import annotations

from quickquip.llm.provider.claude_web_search import (
    CLAUDE_WEB_SEARCH_MAX_USES,
    CLAUDE_WEB_SEARCH_TOOL_NAME,
    CLAUDE_WEB_SEARCH_TOOL_TYPE,
    build_claude_web_search_tool,
    extract_claude_web_search_report,
)


def test_build_claude_web_search_tool_defaults():
    assert build_claude_web_search_tool() == {
        "type": CLAUDE_WEB_SEARCH_TOOL_TYPE,
        "name": CLAUDE_WEB_SEARCH_TOOL_NAME,
        "max_uses": CLAUDE_WEB_SEARCH_MAX_USES,
    }


def test_extract_claude_web_search_report_prioritizes_citations_and_strips_encrypted():
    content = [
        {
            "type": "server_tool_use",
            "id": "srvtoolu_1",
            "name": "web_search",
            "input": {"query": "latest python 3.13 release"},
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_1",
            "content": [
                {
                    "type": "web_search_result",
                    "title": "Uncited Docs",
                    "url": "https://example.org/uncited",
                    "encrypted_content": "SECRET_CIPHERTEXT_1",
                },
                {
                    "type": "web_search_result",
                    "title": "Python 3.13.18 Release",
                    "url": "https://www.python.org/downloads/release/python-31318/",
                    "encrypted_content": "SECRET_CIPHERTEXT_2",
                },
                {
                    "type": "web_search_result",
                    "title": "Bad Scheme",
                    "url": "javascript:alert(1)",
                },
            ],
        },
        {
            "type": "text",
            "text": "The latest release is Python 3.13.18.",
            "citations": [
                {
                    "type": "web_search_result_location",
                    "cited_text": "Python 3.13.18 Release date",
                    "url": "https://www.python.org/downloads/release/python-31318/",
                    "title": "",
                    "encrypted_index": "ENC_IDX",
                }
            ],
        },
    ]
    usage = {"server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 0}}
    report = extract_claude_web_search_report(content, usage)
    assert report is not None
    assert report.queries == ["latest python 3.13 release"]
    assert report.link_urls is True
    # Cited URL comes first and inherits title from matching result entry.
    assert [(s.title, s.url) for s in report.sources] == [
        ("Python 3.13.18 Release", "https://www.python.org/downloads/release/python-31318/"),
        ("Uncited Docs", "https://example.org/uncited"),
    ]
    assert report.raw_metadata is not None
    assert report.raw_metadata["server_tool_use"] == {
        "web_search_requests": 1,
        "web_fetch_requests": 0,
    }
    assert "SECRET_CIPHERTEXT" not in str(report.raw_metadata)
    assert "ENC_IDX" not in str(report.raw_metadata)


def test_extract_claude_web_search_report_handles_error_result_and_plain_replies():
    plain = [{"type": "text", "text": "hello"}]
    assert extract_claude_web_search_report(plain) is None
    assert extract_claude_web_search_report(None) is None

    errored = [
        {
            "type": "server_tool_use",
            "id": "srvtoolu_err",
            "name": "web_search",
            "input": {"query": "some query"},
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_err",
            "content": {"type": "web_search_tool_result_error", "error_code": "unavailable"},
        },
        {"type": "text", "text": "Sorry, search unavailable."},
    ]
    report = extract_claude_web_search_report(errored)
    assert report is not None
    assert report.queries == ["some query"]
    assert report.sources == []
