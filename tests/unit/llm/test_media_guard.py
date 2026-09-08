"""media_guard：GIF 首帧化、MIME 归一、内容去重与字节预算（issue #228）。"""
from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image

from plugins.llm_config import ProviderConfig
from quickquip.llm.provider.base import BaseProviderClient
from quickquip.llm.provider.media_guard import (
    MAX_IMAGE_BYTES,
    guard_inline_media,
)
from quickquip.llm.tools import LLMInlineImage


def _animated_gif(first=(0, 0, 0), second=(255, 255, 255)) -> bytes:
    frames = [Image.new("RGB", (6, 6), first), Image.new("RGB", (6, 6), second)]
    buf = BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


def _png_bytes(color=(1, 2, 3)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


def _still(label: str, size: int, fill: bytes = b"x") -> tuple[str, bytes, str]:
    # 声明 image/png 的静态图走直通路径（不解码）；fill 区分内容避免被去重。
    return label, fill * size, "image/png"


def _make_config(**overrides) -> ProviderConfig:
    defaults = dict(
        id="test",
        protocol="openai",
        base_url="http://test",
        api_key_env="TEST_KEY",
        default_model="m",
        models=["m"],
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


def test_gif_transcoded_to_first_frame_png():
    # 黑白双帧 GIF：转码产物必须是 PNG 且取第一帧（黑），而非末帧。
    kept, dropped = guard_inline_media([("meme.gif", _animated_gif(), "image/gif")], 0)
    assert dropped == []
    assert len(kept) == 1
    assert kept[0].media_type == "image/png"
    with Image.open(BytesIO(kept[0].data)) as img:
        assert img.format == "PNG"
        pixel = img.convert("RGB").getpixel((0, 0))
    assert sum(pixel) < 180  # 首帧为黑


def test_gif_magic_wins_over_declared_media_type():
    # CDN content-type 不可信：魔数是 GIF 就转码，声明是什么不重要。
    kept, _ = guard_inline_media([("labeled.jpeg", _animated_gif(), "image/jpeg")], 0)
    assert [item.media_type for item in kept] == ["image/png"]


def test_valid_still_passes_through_unchanged():
    raw = b"\x89PNG-not-validated-payload"
    kept, dropped = guard_inline_media([("shot.png", raw, "image/png")], 0)
    assert dropped == []
    assert kept[0].data == raw
    assert kept[0].media_type == "image/png"


def test_empty_media_type_sniffed_from_bytes():
    kept, dropped = guard_inline_media([("mystery", _png_bytes(), "")], 0)
    assert dropped == []
    assert kept[0].media_type == "image/png"


def test_unidentifiable_media_dropped():
    kept, dropped = guard_inline_media([("garbage.bin", b"\x00\x01\x02", "")], 0)
    assert kept == []
    assert dropped == ["garbage.bin"]


def test_empty_data_dropped():
    kept, dropped = guard_inline_media([("blank.png", b"", "image/png")], 0)
    assert kept == []
    assert dropped == ["blank.png"]


def test_broken_gif_dropped():
    kept, dropped = guard_inline_media([("truncated.gif", b"GIF89a" + b"\x00" * 32, "image/gif")], 0)
    assert kept == []
    assert dropped == ["truncated.gif"]


def test_duplicate_content_deduped_by_hash():
    png = _png_bytes()
    kept, dropped = guard_inline_media(
        [("url-a", png, "image/png"), ("url-b", png, "image/png")], 0
    )
    # 不同 URL 相同字节（09-08 事故：两张逐字节相同的 3.46MB GIF）只保留首份。
    assert [item.label for item in kept] == ["url-a"]
    assert dropped == ["url-b"]


def test_identical_gifs_deduped_after_transcode():
    gif = _animated_gif()
    kept, dropped = guard_inline_media(
        [("a.gif", gif, "image/gif"), ("b.gif", gif, "image/gif")], 0
    )
    assert [item.label for item in kept] == ["a.gif"]
    assert dropped == ["b.gif"]


def test_budget_keeps_order_and_scans_past_oversized():
    candidates = [_still("big1", 10, b"x"), _still("big2", 10, b"y"), _still("small", 4, b"z")]
    kept, dropped = guard_inline_media(candidates, 15)
    # 10 保留（累计 10），第二张 10 会超（20 > 15）跳过，随后 4 仍可入选（14 ≤ 15）。
    assert [item.label for item in kept] == ["big1", "small"]
    assert dropped == ["big2"]


def test_budget_zero_means_unlimited():
    candidates = [_still(f"img{i}", 1000, bytes([0x61 + i])) for i in range(5)]
    kept, dropped = guard_inline_media(candidates, 0)
    assert dropped == []
    assert len(kept) == 5


def test_single_image_over_cap_dropped():
    huge = b"y" * (MAX_IMAGE_BYTES + 1)
    kept, dropped = guard_inline_media([("huge.png", huge, "image/png")], 0)
    assert kept == []
    assert dropped == ["huge.png"]


def test_transcode_cache_reuses_result(monkeypatch):
    from quickquip.llm.provider import media_guard

    media_guard._transcode_cache.clear()  # 模块级缓存可能已被先前测试预热
    calls: list[bytes] = []
    original = media_guard._gif_first_frame_png

    def counting(raw: bytes) -> bytes | None:
        calls.append(raw)
        return original(raw)

    monkeypatch.setattr(media_guard, "_gif_first_frame_png", counting)
    gif = _animated_gif()
    first, _ = guard_inline_media([("a.gif", gif, "image/gif")], 0)
    second, _ = guard_inline_media([("b.gif", gif, "image/gif")], 0)
    assert len(calls) == 1  # 工具循环逐轮序列化只解码一次
    assert first[0].data == second[0].data


async def test_prepare_image_inputs_guards_inline_images():
    # 三张内联图：重复 GIF ×2 + 真 PNG → 去重后 2 份，GIF 变 PNG。
    client = BaseProviderClient(_make_config())
    gif = _animated_gif()
    result = await client._prepare_image_inputs(
        [],
        [
            LLMInlineImage(data=gif, media_type="image/gif", source_label="meme-1"),
            LLMInlineImage(data=gif, media_type="image/gif", source_label="meme-2"),
            LLMInlineImage(data=_png_bytes(), media_type="image/png", source_label="shot"),
        ],
    )
    assert [item.source_url for item in result] == ["meme-1", "shot"]
    assert all(item.media_type == "image/png" for item in result)
    with Image.open(BytesIO(base64.b64decode(result[0].data_base64))) as img:
        assert img.format == "PNG"


async def test_prepare_image_inputs_applies_configured_budget(monkeypatch):
    client = BaseProviderClient(_make_config(max_inline_media_bytes=1))
    result = await client._prepare_image_inputs(
        [], [LLMInlineImage(data=b"ab", media_type="image/png", source_label="ok")]
    )
    assert result == []  # 预算 1 字节，2 字节图被丢弃

    unlimited = BaseProviderClient(_make_config(max_inline_media_bytes=0))
    result = await unlimited._prepare_image_inputs(
        [], [LLMInlineImage(data=b"ab", media_type="image/png", source_label="ok")]
    )
    assert [item.source_url for item in result] == ["ok"]
