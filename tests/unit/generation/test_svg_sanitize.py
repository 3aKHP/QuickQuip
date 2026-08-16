from __future__ import annotations

import pytest

from quickquip.generation.svg_sanitize import (
    MAX_NESTING_DEPTH,
    SvgSanitizeError,
    extract_visible_text,
    lenient_viewbox,
    parse_viewbox,
    sanitize_svg,
    strip_root_size_attrs,
)


def _wrap(body: str = "", viewBox: str = "0 0 100 100") -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewBox}">{body}</svg>'


class TestSanitizeSvg:
    def test_strips_script_and_event_attrs(self):
        svg = _wrap(
            '<rect width="10" height="10" onload="alert(1)" onclick="x()"/>'
            '<script>alert(2)</script>'
        )
        cleaned = sanitize_svg(svg)
        assert "<script" not in cleaned.lower()
        assert "onload" not in cleaned
        assert "onclick" not in cleaned

    def test_strips_foreign_object_block(self):
        cleaned = sanitize_svg(
            _wrap('<foreignObject width="10" height="10"><div>html</div></foreignObject>')
        )
        assert "foreignObject" not in cleaned

    def test_rejects_unclosed_script(self):
        with pytest.raises(SvgSanitizeError, match="未闭合"):
            sanitize_svg(_wrap("<script>alert(1)"))

    def test_rejects_doctype_and_entities(self):
        with pytest.raises(SvgSanitizeError):
            sanitize_svg('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "b">]>' + _wrap())
        with pytest.raises(SvgSanitizeError):
            sanitize_svg('<!doctype svg public "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/svg.dtd">' + _wrap())
        with pytest.raises(SvgSanitizeError):
            sanitize_svg("<!ENTITY xx 'yy'>" + _wrap())

    def test_rejects_oversize_input(self):
        with pytest.raises(SvgSanitizeError, match="大小上限"):
            sanitize_svg(_wrap() + "<!--" + "x" * (64 * 1024) + "-->")

    def test_rejects_deep_nesting(self):
        depth = MAX_NESTING_DEPTH + 10
        with pytest.raises(SvgSanitizeError, match="嵌套深度"):
            sanitize_svg("<svg>" + "<g>" * depth + "</g>" * depth + "</svg>")

    def test_self_closing_tags_do_not_accumulate_depth(self):
        depth = MAX_NESTING_DEPTH // 2
        svg = "<svg viewBox=\"0 0 10 10\">" + '<rect width="1" height="1"/>' * depth + "</svg>"
        sanitize_svg(svg)  # 不应抛错

    def test_drops_external_href_keeps_fragment(self):
        cleaned = sanitize_svg(
            _wrap(
                '<use href="#shape"/>'
                '<image href="http://evil.test/x.png" width="1" height="1"/>'
                "<image xlink:href='file:///etc/passwd' width='1' height='1'/>"
            )
        )
        assert 'href="#shape"' in cleaned
        assert "http://evil.test" not in cleaned
        assert "file:///etc/passwd" not in cleaned

    def test_filter_param_limits(self):
        with pytest.raises(SvgSanitizeError, match="numOctaves"):
            sanitize_svg(_wrap('<filter id="f"><feTurbulence numOctaves="8"/></filter>'))
        with pytest.raises(SvgSanitizeError, match="stdDeviation"):
            sanitize_svg(_wrap('<filter id="f"><feGaussianBlur stdDeviation="500"/></filter>'))
        with pytest.raises(SvgSanitizeError, match="baseFrequency"):
            sanitize_svg(_wrap('<filter id="f"><feTurbulence baseFrequency="0.0001"/></filter>'))
        with pytest.raises(SvgSanitizeError, match="filter"):
            sanitize_svg(_wrap('<filter id="f" x="-100%" y="0" width="500%" height="100%"><feGaussianBlur stdDeviation="1"/></filter>'))


class TestParseViewbox:
    def test_parses_valid_viewbox(self):
        assert parse_viewbox(_wrap(viewBox="0 0 640 360")) == (640, 360)

    def test_comma_separated(self):
        assert parse_viewbox(_wrap(viewBox="0,0,300,200")) == (300, 200)

    def test_missing_viewbox_falls_back(self):
        assert parse_viewbox("<svg xmlns='http://www.w3.org/2000/svg'/>") == (512, 512)

    def test_rejects_oversize(self):
        with pytest.raises(SvgSanitizeError, match="不能超过"):
            parse_viewbox(_wrap(viewBox="0 0 4096 100"))

    def test_rejects_non_positive(self):
        with pytest.raises(SvgSanitizeError, match="正数"):
            parse_viewbox(_wrap(viewBox="0 0 0 100"))

    def test_lenient_clamps_instead_of_rejecting(self):
        assert lenient_viewbox(_wrap(viewBox="0 0 99999 100")) == (2048, 100)
        assert lenient_viewbox("<svg/>") is None
        assert lenient_viewbox(_wrap(viewBox="0 0 -5 100")) is None


class TestStripRootSizeAttrs:
    def test_strips_only_root_tag_sizes(self):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="99999" height="99999" viewBox="0 0 120 60">'
            '<rect width="10" height="10"/></svg>'
        )
        cleaned = strip_root_size_attrs(svg)
        assert 'width="99999"' not in cleaned
        assert 'viewBox="0 0 120 60"' in cleaned
        assert '<rect width="10" height="10"/>' in cleaned

    def test_keeps_unquoted_and_single_quoted(self):
        cleaned = strip_root_size_attrs("<svg width=99999 height='88888' viewBox='0 0 1 1'><rect width='2' height='2'/></svg>")
        assert "99999" not in cleaned.split("<rect")[0]
        assert "<rect width='2' height='2'/>" in cleaned

    def test_no_svg_tag_returns_unchanged(self):
        assert strip_root_size_attrs("<div width='10'></div>") == "<div width='10'></div>"


class TestExtractVisibleText:
    def test_extracts_text_and_tspan_with_entities(self):
        svg = _wrap(
            '<text x="0" y="10">你好 &amp; 再见</text>'
            '<text><tspan>第二行</tspan><tspan dy="10">第三行</tspan></text>'
        )
        text = extract_visible_text(svg)
        assert "你好 & 再见" in text
        assert "第二行" in text
        assert "第三行" in text

    def test_empty_when_no_text(self):
        assert extract_visible_text(_wrap("<rect width='1' height='1'/>")) == ""
