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
#   - qq_id: "1000000000"
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


def test_load_index_accepts_special_accounts_placeholder(tmp_path: Path):
    """special_accounts 段的占位条目（qq_id 与标准名均空）同样按空白处理。"""
    path = tmp_path / "identities.yaml"
    path.write_text(
        'special_accounts:\n'
        '  - qq_id: ""\n'
        '    canonical_name:\n',
        encoding="utf-8",
    )

    index = _load_index(path)

    assert index.entries == []


def test_load_index_parses_special_accounts_entry(tmp_path: Path):
    """special_accounts 的实质条目走 qq_id 单数字段正常解析。"""
    path = tmp_path / "identities.yaml"
    path.write_text(
        'special_accounts:\n'
        '  - qq_id: "1000000000"\n'
        '    canonical_name: Bot\n',
        encoding="utf-8",
    )

    index = _load_index(path)

    assert [entry.canonical_name for entry in index.entries] == ["Bot"]


def test_load_index_accepts_scalar_qq_ids(tmp_path: Path):
    """qq_ids 写成未加引号的标量时按单元素列表归一化，正常解析。"""
    path = tmp_path / "identities.yaml"
    path.write_text(
        'people:\n'
        '  - canonical_name: 张三\n'
        '    qq_ids: 10001\n',
        encoding="utf-8",
    )

    index = _load_index(path)

    assert [entry.qq_ids for entry in index.entries] == [["10001"]]


def test_load_index_raises_on_scalar_qq_ids_without_name(tmp_path: Path):
    """标量 qq_ids 配空标准名属于实质声明的半成品，保持报错。"""
    path = tmp_path / "identities.yaml"
    path.write_text(
        'people:\n'
        '  - canonical_name:\n'
        '    qq_ids: 10001\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no valid entries"):
        _load_index(path)
