from __future__ import annotations

import io
from pathlib import Path

import pytest
import wordcloud
from PIL import Image

from quickquip.common import text_image
from quickquip.common.text_image import find_cjk_font_path, render_text_to_image

_BUNDLED_TEST_FONT = Path(wordcloud.__file__).parent / "DroidSansMono.ttf"


def test_render_text_to_image_returns_valid_png():
    content = (
        "# 群聊日报 · 2026-11-21\n\n"
        "今天大家讨论了 **架构重构** 与 `OneBot V11` 协议。\n\n"
        "## 主要话题\n\n"
        "- 第一项话题：合并转发失败改为单张长图发送，避免刷屏。\n"
        "- 第二项话题：支持英文长串 https://example.com/very/long/path/without/spaces/abcdef123456。\n\n"
        "> 引用段落测试：一行正常中文与 English 混排。\n"
    )

    png_bytes = render_text_to_image(
        content,
        title="群聊日报",
        footer="合并转发不可用，已转为长图发送",
        font_path=_BUNDLED_TEST_FONT,
    )

    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    with Image.open(io.BytesIO(png_bytes)) as img:
        assert img.format == "PNG"
        assert img.width == 900
        assert img.height >= 200


def test_render_text_to_image_respects_max_height():
    long_content = "\n\n".join(
        f"第 {i} 段：这是一段用于测试高度截断保护的中文内容。" * 4 for i in range(60)
    )

    png_bytes = render_text_to_image(
        long_content,
        title="群聊日报",
        max_height=1200,
        font_path=_BUNDLED_TEST_FONT,
    )

    with Image.open(io.BytesIO(png_bytes)) as img:
        assert img.height <= 1200


def test_find_cjk_font_path_missing_explicit_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_cjk_font_path(tmp_path / "missing.ttf")


def test_find_cjk_font_path_missing_all_candidates_raises(monkeypatch):
    monkeypatch.setattr(text_image, "_CANDIDATE_FONT_PATHS", ())
    monkeypatch.setattr(text_image, "_find_font_via_fc_match", lambda: None)

    with pytest.raises(FileNotFoundError, match="未找到可用的中文字体文件"):
        find_cjk_font_path()


def test_find_cjk_font_path_falls_back_to_fc_match(monkeypatch):
    monkeypatch.setattr(text_image, "_CANDIDATE_FONT_PATHS", ())
    monkeypatch.setattr(text_image, "_find_font_via_fc_match", lambda: _BUNDLED_TEST_FONT)

    assert find_cjk_font_path() == _BUNDLED_TEST_FONT
