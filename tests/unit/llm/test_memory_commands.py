from quickquip.common.record_content import plain, references, render
from quickquip.llm.memory_commands import write_arguments, list_arguments


def test_overwrite_preserves_mentions_and_markdown():
    body = {
        "version": 1,
        "parts": [
            {"type": "text", "text": "--id 42 # 约定\n\n"},
            {"type": "member", "qq": "12345", "name": "小明", "usage": "mention"},
            {"type": "text", "text": " 每周六组织联机。"},
        ],
    }
    ident, result = write_arguments(body)
    assert ident == 42
    assert render(result).startswith("# 约定\n\n")
    assert references(result) == {"12345"}
    assert body["parts"][0]["text"].startswith("--id 42")


def test_escaped_flags_and_paged_query():
    ident, body = write_arguments(plain("-- --id 42 是一个示例"))
    assert ident is None and render(body) == "--id 42 是一个示例"
    assert list_arguments("-- --id 42") == (None, 1, "--id 42")
    assert list_arguments("--page 2 联机安排") == (None, 2, "联机安排")
    assert list_arguments("42") == (None, 1, "42")
