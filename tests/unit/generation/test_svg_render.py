from __future__ import annotations

import io

import pytest

from quickquip.generation.svg import SvgRenderError, SvgSanitizeError, render_svg_to_png

_GOOD_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60">
<rect width="120" height="60" fill="#4e79a7"/>
<text x="60" y="40" font-size="20" text-anchor="middle" fill="#fff">测试</text>
</svg>"""


def _png_size(png: bytes) -> tuple[int, int]:
    from PIL import Image

    return Image.open(io.BytesIO(png)).size


async def test_render_happy_path():
    png = await render_svg_to_png(_GOOD_SVG)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert _png_size(png) == (240, 120)  # viewBox × 2


async def test_render_ignores_svg_width_height_attributes():
    bomb = _GOOD_SVG.replace(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60">',
        '<svg xmlns="http://www.w3.org/2000/svg" width="99999" height="99999" viewBox="0 0 120 60">',
    )
    png = await render_svg_to_png(bomb)
    assert _png_size(png) == (240, 120)


async def test_render_rejects_oversize_viewbox_when_hardened():
    with pytest.raises(SvgSanitizeError):
        await render_svg_to_png(_GOOD_SVG.replace("0 0 120 60", "0 0 99999 60"))


async def test_render_lenient_mode_clamps():
    png = await render_svg_to_png(
        _GOOD_SVG.replace("0 0 120 60", "0 0 99999 60"), harden=False
    )
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


async def test_render_propagates_worker_error():
    with pytest.raises(SvgRenderError):
        await render_svg_to_png("这不是一段 SVG 文档")
