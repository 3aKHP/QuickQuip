"""长文本渲染为单张长图（PNG bytes）。

用于群聊合并转发（send_group_forward_msg）失败时的无刷屏降级：将多段长文
排版为单张浅色卡片 PNG，既避免连续多条纯文本刷屏，也能绕过部分纯文本风控拦截。
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

from quickquip.common.paths import DATA_DIR

_DEFAULT_CANVAS_WIDTH = 900
_OUTER_PAD_X = 28
_OUTER_PAD_Y = 28
_CARD_PAD_X = 40
_CARD_PAD_Y = 36
_MAX_IMAGE_HEIGHT = 14000

_BG_OUTER = (244, 245, 247)
_BG_CARD = (255, 255, 255)
_BORDER_CARD = (226, 232, 240)
_ACCENT_BAR = (59, 130, 246)
_DIVIDER_COLOR = (229, 231, 235)
_TEXT_TITLE = (17, 24, 39)
_TEXT_HEADING = (15, 23, 42)
_TEXT_BODY = (31, 41, 55)
_TEXT_QUOTE = (75, 85, 99)
_TEXT_MUTED = (107, 114, 128)
_QUOTE_BAR = (156, 163, 175)

_INLINE_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
_BULLET_RE = re.compile(r"^[-*•]\s+(.+)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")

_CANDIDATE_FONT_PATHS: tuple[Path, ...] = (
    DATA_DIR / "fonts" / "NotoSansSC-Regular.ttf",
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/unifont/unifont.otf"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/System/Library/Fonts/PingFang.ttc"),
)


@dataclass(frozen=True)
class _LayoutLine:
    text: str
    kind: str  # "h1" | "h2" | "h3" | "body" | "quote" | "spacer"
    indent: int = 0


def find_cjk_font_path(font_path: str | Path | None = None) -> Path:
    """查找可用的中文字体文件；全部缺失时抛出 FileNotFoundError。"""
    if font_path is not None:
        explicit = Path(font_path)
        if explicit.is_file():
            return explicit
        raise FileNotFoundError(f"指定的字体文件不存在：{explicit}")

    for candidate in _CANDIDATE_FONT_PATHS:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "未找到可用的中文字体文件（已检查 data/fonts/NotoSansSC-Regular.ttf 及系统常见字体路径）"
    )


def _clean_inline_markdown(text: str) -> str:
    text = _INLINE_BOLD_RE.sub(r"\1", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    return text


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    """按像素宽度精确折行，兼容中英文混排与无空格长串。"""
    if not text:
        return [""]

    lines: list[str] = []
    current = ""
    for ch in text:
        candidate = current + ch
        if current and font.getlength(candidate) > max_width:
            lines.append(current)
            current = ch
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _build_layout_lines(
    content: str,
    *,
    fonts: dict[str, object],
    content_width: int,
) -> list[_LayoutLine]:
    raw_lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    layout: list[_LayoutLine] = []
    prev_blank = False

    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped:
            if layout and not prev_blank:
                layout.append(_LayoutLine(text="", kind="spacer"))
                prev_blank = True
            continue

        prev_blank = False

        heading_match = _HEADING_RE.match(stripped)
        if heading_match:
            level = len(heading_match.group(1))
            kind = f"h{level}"
            clean = _clean_inline_markdown(heading_match.group(2).strip())
            if layout and layout[-1].kind != "spacer":
                layout.append(_LayoutLine(text="", kind="spacer"))
            for wrapped in _wrap_text(clean, fonts[kind], content_width):
                layout.append(_LayoutLine(text=wrapped, kind=kind))
            continue

        quote_match = _QUOTE_RE.match(stripped)
        if quote_match:
            clean = _clean_inline_markdown(quote_match.group(1).strip())
            quote_indent = 20
            for wrapped in _wrap_text(clean, fonts["body"], content_width - quote_indent):
                layout.append(_LayoutLine(text=wrapped, kind="quote", indent=quote_indent))
            continue

        bullet_match = _BULLET_RE.match(stripped)
        if bullet_match:
            clean = "• " + _clean_inline_markdown(bullet_match.group(1).strip())
            bullet_indent = 12
            for idx, wrapped in enumerate(
                _wrap_text(clean, fonts["body"], content_width - bullet_indent)
            ):
                layout.append(
                    _LayoutLine(
                        text=wrapped,
                        kind="body",
                        indent=bullet_indent if idx == 0 else bullet_indent + 24,
                    )
                )
            continue

        clean = _clean_inline_markdown(stripped)
        for wrapped in _wrap_text(clean, fonts["body"], content_width):
            layout.append(_LayoutLine(text=wrapped, kind="body"))

    while layout and layout[-1].kind == "spacer":
        layout.pop()

    return layout


def render_text_to_image(
    content: str,
    *,
    title: str = "",
    footer: str = "",
    font_path: str | Path | None = None,
    width: int = _DEFAULT_CANVAS_WIDTH,
    max_height: int = _MAX_IMAGE_HEIGHT,
) -> bytes:
    """将长文本渲染为单张浅色卡片长图（PNG bytes）。

    当内容高度超过 ``max_height`` 时会在末尾截断并附加提示行，避免超巨图片
    导致内存暴涨或协议端拒收。
    """
    from PIL import Image, ImageDraw, ImageFont  # lazy import

    resolved_font = find_cjk_font_path(font_path)
    fonts = {
        "title": ImageFont.truetype(str(resolved_font), 30),
        "h1": ImageFont.truetype(str(resolved_font), 32),
        "h2": ImageFont.truetype(str(resolved_font), 28),
        "h3": ImageFont.truetype(str(resolved_font), 26),
        "body": ImageFont.truetype(str(resolved_font), 24),
        "footer": ImageFont.truetype(str(resolved_font), 19),
    }
    line_heights = {
        "h1": 46,
        "h2": 42,
        "h3": 38,
        "body": 38,
        "quote": 36,
        "spacer": 16,
    }

    card_left = _OUTER_PAD_X
    card_right = width - _OUTER_PAD_X
    content_left = card_left + _CARD_PAD_X
    content_width = (card_right - card_left) - 2 * _CARD_PAD_X

    layout = _build_layout_lines(content, fonts=fonts, content_width=content_width)

    header_height = 56 if title else 0
    footer_height = 46 if footer else 0
    fixed_vertical = 2 * _OUTER_PAD_Y + 2 * _CARD_PAD_Y + header_height + footer_height

    max_body_height = max(200, max_height - fixed_vertical)
    rendered_lines: list[_LayoutLine] = []
    body_height = 0
    truncated = False

    for line in layout:
        h = line_heights[line.kind]
        if body_height + h > max_body_height:
            truncated = True
            break
        rendered_lines.append(line)
        body_height += h

    if truncated:
        notice_h = line_heights["body"] + line_heights["spacer"]
        while rendered_lines and body_height + notice_h > max_body_height:
            popped = rendered_lines.pop()
            body_height -= line_heights[popped.kind]
        rendered_lines.append(_LayoutLine(text="", kind="spacer"))
        rendered_lines.append(
            _LayoutLine(text="……（内容过长已截断，完整内容请在后台查看）", kind="quote")
        )
        body_height += line_heights["spacer"] + line_heights["quote"]

    total_height = max(200, fixed_vertical + body_height)
    image = Image.new("RGB", (width, total_height), _BG_OUTER)
    draw = ImageDraw.Draw(image)

    card_top = _OUTER_PAD_Y
    card_bottom = total_height - _OUTER_PAD_Y
    draw.rounded_rectangle(
        (card_left, card_top, card_right, card_bottom),
        radius=16,
        fill=_BG_CARD,
        outline=_BORDER_CARD,
        width=2,
    )

    y = card_top + _CARD_PAD_Y
    if title:
        draw.rounded_rectangle(
            (content_left, y + 4, content_left + 7, y + 34),
            radius=3,
            fill=_ACCENT_BAR,
        )
        draw.text((content_left + 18, y), title, font=fonts["title"], fill=_TEXT_TITLE)
        y += 44
        draw.line((content_left, y, card_right - _CARD_PAD_X, y), fill=_DIVIDER_COLOR, width=2)
        y += 12

    for line in rendered_lines:
        if line.kind == "spacer":
            y += line_heights["spacer"]
            continue

        x = content_left + line.indent
        if line.kind in ("h1", "h2", "h3"):
            draw.text((x, y), line.text, font=fonts[line.kind], fill=_TEXT_HEADING)
        elif line.kind == "quote":
            draw.rectangle(
                (content_left + 4, y + 4, content_left + 8, y + line_heights["quote"] - 6),
                fill=_QUOTE_BAR,
            )
            draw.text((x, y), line.text, font=fonts["body"], fill=_TEXT_QUOTE)
        else:
            draw.text((x, y), line.text, font=fonts["body"], fill=_TEXT_BODY)
        y += line_heights[line.kind]

    if footer:
        y += 10
        draw.line((content_left, y, card_right - _CARD_PAD_X, y), fill=_DIVIDER_COLOR, width=1)
        y += 12
        draw.text((content_left, y), footer, font=fonts["footer"], fill=_TEXT_MUTED)

    buf = io.BytesIO()
    quantized = image.quantize(
        colors=64, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE
    )
    quantized.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
