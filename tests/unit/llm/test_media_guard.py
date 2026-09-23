"""media_guard：GIF 首帧化、MIME 归一、内容去重与字节预算（issue #228）。"""

from __future__ import annotations

import base64
import random
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


def _noise_png(width=1200, height=800, seed=7) -> bytes:
    # 逐像素随机：PNG/JPEG 都压不动的最坏情况，字节数由 seed 决定、跨运行稳定。
    rng = random.Random(seed)
    img = Image.new("RGB", (width, height))
    img.putdata(
        [
            (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            for _ in range(width * height)
        ]
    )
    buf = BytesIO()
    img.save(buf, format="PNG")
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
    kept, dropped = guard_inline_media(
        [("truncated.gif", b"GIF89a" + b"\x00" * 32, "image/gif")], 0
    )
    assert kept == []
    assert dropped == ["truncated.gif"]


def test_decompression_bomb_gif_dropped_not_raised():
    # 篡改逻辑屏幕描述符为 20000x20000（~50 字节改动，远小于单图上限）：
    # 必须丢弃该图，不得让 DecompressionBombError 逃逸炸掉整个请求。
    gif = bytearray(_animated_gif())
    gif[6:10] = (20000).to_bytes(2, "little") + (20000).to_bytes(2, "little")
    kept, dropped = guard_inline_media([("bomb.gif", bytes(gif), "image/gif")], 0)
    assert kept == []
    assert dropped == ["bomb.gif"]


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


def test_budget_stops_at_first_overflow():
    # 前缀止停：候选顺序即优先级（当前→引用→近期），第一张装不下
    # 连同其后全部丢弃——避免丢当前大图却保留后续无关小图让模型看错图。
    candidates = [_still("big1", 10, b"x"), _still("big2", 10, b"y"), _still("small", 4, b"z")]
    kept, dropped = guard_inline_media(candidates, 15)
    assert [item.label for item in kept] == ["big1"]
    assert dropped == ["big2", "small"]


def test_budget_lone_oversized_image_drops_everything():
    candidates = [_still("huge", 100, b"x"), _still("small", 4, b"z")]
    kept, dropped = guard_inline_media(candidates, 50)
    assert kept == []
    assert dropped == ["huge", "small"]


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


# ── 超限适配：压缩代替丢弃（2026-09 生产事故后引入） ──────────────────────
# 噪声图 1200x800（seed=7）的实测阶梯：PNG ≈ 2.88MB、原尺寸 q85 ≈ 726KB、
# 长边 768 q70 ≈ 149KB。下方各预算据此锚定行为分支；锚点余量约 25%，
# 依赖 uv.lock 锁定的 Pillow 编码器输出——升级 Pillow 后若分支判定翻转，
# 按新版实测重新锚定。


def test_budget_overflow_compresses_without_resize():
    # 1MB 额度装不下 2.88MB PNG，但原尺寸 q85 JPEG（≈726KB）可达标：
    # 保真优先，不触发长边阶梯。
    kept, dropped = guard_inline_media([("shot.png", _noise_png(), "image/png")], 1_000_000)
    assert dropped == []
    assert len(kept) == 1
    assert kept[0].media_type == "image/jpeg"
    assert len(kept[0].data) <= 1_000_000
    with Image.open(BytesIO(kept[0].data)) as img:
        assert img.size == (1200, 800)


def test_budget_overflow_resizes_when_quality_alone_insufficient():
    # 200KB 额度：质量阶梯走完仍不够，长边降到 768 才命中。
    kept, dropped = guard_inline_media([("shot.png", _noise_png(), "image/png")], 200_000)
    assert dropped == []
    assert kept[0].media_type == "image/jpeg"
    assert len(kept[0].data) <= 200_000
    with Image.open(BytesIO(kept[0].data)) as img:
        assert 0 < img.width < 1200
        assert 0 < img.height < 800
        assert img.width * 800 == img.height * 1200


def test_budget_overflow_incompressible_drops_prefix():
    # 120KB 额度高于压缩下限（96KB）但阶梯压不进：回退为前缀止停丢弃。
    candidates = [
        ("shot.png", _noise_png(), "image/png"),
        ("tiny.png", _png_bytes(), "image/png"),
    ]
    kept, dropped = guard_inline_media(candidates, 120_000)
    assert kept == []
    assert dropped == ["shot.png", "tiny.png"]


def test_duplicate_content_deduped_after_compression():
    # 第二张的压缩目标额度是剩余额度（≈1.27MB），与首张（2MB）不同、
    # 压缩缓存必 miss；但两者都高于原尺寸 q85 档（≈726KB），重压缩命中
    # 同一档产出同字节，内容哈希去重成立——额度低于该档时产物字节不同、
    # 去重不成立（属预期）。
    raw = _noise_png(seed=21)
    kept, dropped = guard_inline_media(
        [("url-a", raw, "image/png"), ("url-b", raw, "image/png")], 2_000_000
    )
    assert [item.label for item in kept] == ["url-a"]
    assert all(item.media_type == "image/jpeg" for item in kept)
    assert dropped == ["url-b"]


def test_single_image_cap_compresses_and_continues(monkeypatch):
    # 单图上限超限同样先压缩；压缩失败才跳过单张、继续处理后续候选。
    from quickquip.llm.provider import media_guard

    monkeypatch.setattr(media_guard, "MAX_IMAGE_BYTES", 800_000)
    candidates = [
        ("huge.png", _noise_png(), "image/png"),  # PNG 2.88MB > 上限 800KB
        ("tiny.png", _png_bytes(), "image/png"),
    ]
    kept, dropped = guard_inline_media(candidates, 0)
    assert dropped == []
    assert [item.label for item in kept] == ["huge.png", "tiny.png"]
    assert kept[0].media_type == "image/jpeg"
    assert len(kept[0].data) <= 800_000
    assert kept[1].data == candidates[1][1]  # 小图原样保留


def test_compress_floor_refuses_tiny_remaining_budget(monkeypatch):
    # 剩余额度低于压缩下限：不再尝试压缩，直接走丢弃路径。
    from quickquip.llm.provider import media_guard

    calls: list[int] = []

    def refuse(raw: bytes, media_type: str, target_bytes: int):
        calls.append(target_bytes)
        return None

    monkeypatch.setattr(media_guard, "_compress_bytes", refuse)
    kept, dropped = guard_inline_media([("shot.png", _noise_png(), "image/png")], 50_000)
    assert kept == []
    assert dropped == ["shot.png"]
    assert calls == []


def test_compress_cache_reuses_result(monkeypatch):
    from quickquip.llm.provider import media_guard

    media_guard._compress_cache.clear()
    calls: list[int] = []
    original = media_guard._compress_bytes

    def counting(raw: bytes, media_type: str, target_bytes: int):
        calls.append(target_bytes)
        return original(raw, media_type, target_bytes)

    monkeypatch.setattr(media_guard, "_compress_bytes", counting)
    raw = _noise_png(seed=11)
    first = media_guard._compress_to_fit(raw, "image/png", 500_000)
    second = media_guard._compress_to_fit(raw, "image/png", 500_000)
    assert len(calls) == 1  # 同图同额度只解码压缩一次
    assert first is not None and first == second


def test_compress_applies_exif_orientation():
    # EXIF Orientation=6（旋转 90°）的手机照片：压缩产物必须是已转正的位图。
    img = Image.new("RGB", (80, 40), (10, 20, 30))
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif)

    from quickquip.llm.provider.media_guard import _compress_to_fit

    fitted = _compress_to_fit(buf.getvalue(), "image/jpeg", 200_000)
    assert fitted is not None
    data, media_type = fitted
    assert media_type == "image/jpeg"
    with Image.open(BytesIO(data)) as result:
        assert result.size == (40, 80)


def test_compress_flattens_alpha_onto_white():
    # 全透明红 PNG：JPEG 无透明通道，透明区平铺白底而非丢弃色彩信息。
    buf = BytesIO()
    Image.new("RGBA", (8, 8), (255, 0, 0, 0)).save(buf, format="PNG")

    from quickquip.llm.provider.media_guard import _compress_to_fit

    fitted = _compress_to_fit(buf.getvalue(), "image/png", 96 * 1024)
    assert fitted is not None
    data, media_type = fitted
    assert media_type == "image/jpeg"
    with Image.open(BytesIO(data)) as result:
        assert result.mode == "RGB"
        assert result.getpixel((0, 0)) == (255, 255, 255)


def test_extreme_aspect_ratio_survives_ladder():
    # 25000x4 合法窄条（实测 PNG ≈293KB，可通过直通）+ 紧预算（100KB）：
    # 原尺寸 q85/q70（≈158/110KB）装不下进入长边阶梯，缩放短边按比例
    # 取整曾得 0 使 ValueError 逃出 guard 炸掉整个请求组装；钳制 ≥1 后
    # 产出 (2560, 1) 有效条带。横竖两种取向都不得抛异常。
    for width, height in ((25000, 4), (4, 25000)):
        kept, dropped = guard_inline_media(
            [("strip.png", _noise_png(width, height), "image/png")], 100_000
        )
        assert dropped == []
        assert len(kept) == 1
        with Image.open(BytesIO(kept[0].data)) as img:
            assert min(img.size) == 1
            assert max(img.size) == 2560


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
