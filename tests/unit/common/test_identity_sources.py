from __future__ import annotations

from pathlib import Path

import pytest

from quickquip.common.identity_sources import _load_index

# 与部署分发的全局模板同形态：people 段只有一个未填写的占位条目，
# special_accounts 整段处于注释状态。
_PLACEHOLDER_TEMPLATE = """# ── QuickQuip 标准身份词表 ──────────────────────────────────────────────
# 复制为 identities.yaml 后按你的群编辑。

people:
  - canonical_name:
    qq_ids:
      - ""
    aliases:
    note:

# special_accounts:
#   - qq_id: "9998887776"
#     canonical_name: Bot
"""


def test_load_index_accepts_placeholder_only_template(tmp_path: Path):
    """只含占位条目的模板按空白文档处理，返回空索引。"""
    path = tmp_path / "identities.yaml"
    path.write_text(_PLACEHOLDER_TEMPLATE, encoding="utf-8")

    index = _load_index(path)

    assert index.entries == []


def test_load_index_accepts_absent_sections(tmp_path: Path):
    """无 people/special_accounts 段的文档同样按空白处理。"""
    path = tmp_path / "identities.yaml"
    path.write_text("# 仅注释\n", encoding="utf-8")

    index = _load_index(path)

    assert index.entries == []


def test_load_index_raises_on_declared_but_unresolvable_entry(tmp_path: Path):
    """声明了实质条目却解析不出任何身份时保持报错（防坏数据顶替有效索引）。"""
    path = tmp_path / "identities.yaml"
    path.write_text(
        'people:\n'
        '  - canonical_name: 张三\n'
        '    qq_ids:\n'
        '      - ""\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no valid entries"):
        _load_index(path)


def test_load_index_parses_entries_alongside_placeholder(tmp_path: Path):
    """占位条目与真实条目并存时照常解析真实条目。"""
    path = tmp_path / "identities.yaml"
    path.write_text(
        _PLACEHOLDER_TEMPLATE
        + '  - canonical_name: 张三\n'
        + '    qq_ids:\n'
        + '      - "10001"\n',
        encoding="utf-8",
    )

    index = _load_index(path)

    assert [entry.canonical_name for entry in index.entries] == ["张三"]
