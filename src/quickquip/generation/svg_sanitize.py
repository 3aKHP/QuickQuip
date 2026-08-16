"""SVG 输入清洗与静态预检。

对 LLM 产出的 SVG 做渲染前的硬约束与清洗。所有检查均在字符串/正则层完成，
不引入任何 XML 解析器（标准库解析器自身存在实体膨胀风险）。真正的 XML 解析
发生在受 rlimit 约束的渲染 worker 子进程内（见 ``svg_worker.py``），本模块
的深度与滤镜检查只是启发式前置，用于尽早给出可回传给模型的明确错误。

属性相关的清洗与检查只作用于标签内部（``<...>`` 区间），避免把文本内容里
出现的 ``href=``、``numOctaves=`` 等字样误当作属性处理。
"""

from __future__ import annotations

import html
import re

MAX_SVG_BYTES = 64 * 1024
MAX_VIEWBOX_SIZE = 2048
DEFAULT_VIEWBOX_SIZE = 512
MAX_NESTING_DEPTH = 2000
MAX_NUM_OCTAVES = 4
MAX_STD_DEVIATION = 50.0
MIN_BASE_FREQUENCY = 0.001
MAX_FILTER_REGION_RATIO = 3.0
MAX_FILTER_REGION_ABS = 8192.0


class SvgSanitizeError(ValueError):
    """SVG 未通过静态预检（原因见消息，可直接回传给模型自修重试）。"""


_SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_FOREIGN_BLOCK_RE = re.compile(
    r"<foreignObject\b[^>]*>.*?</foreignObject\s*>", re.IGNORECASE | re.DOTALL
)
# 属性值的三种引号形态；所有属性级检查统一经 _iter_tag_bodies 锚定到标签内
_EVENT_ATTR_RE = re.compile(r"""\s+on[a-zA-Z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")
_HREF_ATTR_RE = re.compile(r"""(\s+(?:xlink:)?href\s*=\s*)("[^"]*"|'[^']*'|[^\s>]+)""", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_VIEWBOX_RE = re.compile(r"""viewBox\s*=\s*(["'])\s*([-\d.eE+,\s]+?)\1""", re.IGNORECASE)
_SVG_ROOT_TAG_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)
_ROOT_SIZE_ATTR_RE = re.compile(
    r"""\s(?:width|height)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)"""
)
_TEXT_BLOCK_RE = re.compile(r"<(text|tspan)\b[^>]*>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)


def sanitize_svg(svg: str) -> str:
    """对渲染前的 SVG 做硬约束检查与惰性内容剥离，违规时抛 SvgSanitizeError。

    剥离仅针对 resvg 本就不执行的载体（script/事件属性/外链），目的是防止
    清洗后的 SVG 在任何二次利用场景（日志、转存）中携带活性载荷。
    """
    if len(svg.encode("utf-8")) > MAX_SVG_BYTES:
        raise SvgSanitizeError(f"SVG 超过大小上限（{MAX_SVG_BYTES // 1024}KB）")
    if re.search(r"<!DOCTYPE|<!ENTITY", svg, re.IGNORECASE):
        raise SvgSanitizeError("不允许 DOCTYPE / ENTITY 声明")
    _check_nesting_depth(svg)
    _check_filter_params(svg)

    cleaned = _map_tag_bodies(svg, _strip_event_and_href_attrs)
    cleaned = _SCRIPT_BLOCK_RE.sub("", cleaned)
    cleaned = _FOREIGN_BLOCK_RE.sub("", cleaned)
    if re.search(r"<script\b|<foreignObject\b", cleaned, re.IGNORECASE):
        raise SvgSanitizeError("存在未闭合的 script/foreignObject，请移除后重试")
    return cleaned


def parse_viewbox(svg: str) -> tuple[int, int]:
    """从 viewBox 推导输出尺寸（宽高上限 MAX_VIEWBOX_SIZE，缺失回退正方形缺省值）。"""
    match = _VIEWBOX_RE.search(svg)
    if match is None:
        return DEFAULT_VIEWBOX_SIZE, DEFAULT_VIEWBOX_SIZE
    parts = re.split(r"[,\s]+", match.group(2).strip())
    if len(parts) != 4:
        raise SvgSanitizeError("viewBox 格式不正确，应为 \"minX minY width height\"")
    try:
        width, height = float(parts[2]), float(parts[3])
    except ValueError as exc:
        raise SvgSanitizeError("viewBox 宽高不是有效数字") from exc
    if width <= 0 or height <= 0:
        raise SvgSanitizeError("viewBox 宽高必须为正数")
    if width > MAX_VIEWBOX_SIZE or height > MAX_VIEWBOX_SIZE:
        raise SvgSanitizeError(f"viewBox 宽高不能超过 {MAX_VIEWBOX_SIZE}")
    return max(1, round(width)), max(1, round(height))


def lenient_viewbox(svg: str) -> tuple[int, int] | None:
    """宽容模式尺寸解析：无效/超限时钳制到上限而非拒绝，供 harden=False 使用。"""
    match = _VIEWBOX_RE.search(svg)
    if match is None:
        return None
    parts = re.split(r"[,\s]+", match.group(2).strip())
    if len(parts) != 4:
        return None
    try:
        width, height = float(parts[2]), float(parts[3])
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    width = max(1, min(MAX_VIEWBOX_SIZE, round(width)))
    height = max(1, min(MAX_VIEWBOX_SIZE, round(height)))
    return width, height


def strip_root_size_attrs(svg: str) -> str:
    """剥离根节点 <svg> 的 width/height 属性，只保留 viewBox。

    resvg 以 SVG 自带 width/height 为内在尺寸参与等比缩放，服务端的输出
    尺寸覆盖（渲染参数 width/height 只是适配画布）必须配合本归一化才能
    精确生效——这也是输出尺寸炸弹防线的组成部分，任何模式下都执行。
    """
    match = _SVG_ROOT_TAG_RE.search(svg)
    if match is None:
        return svg
    root_tag = _ROOT_SIZE_ATTR_RE.sub("", match.group(0))
    return svg[: match.start()] + root_tag + svg[match.end() :]


def extract_visible_text(svg: str) -> str:
    """提取 <text>/<tspan> 的可见文本，供敏感词扫描与内容裁决使用。

    先展开 CDATA 定界（resvg 会渲染其中内容，不能让扫描层看不见），
    再清掉嵌套标签并做实体反转义。
    """
    chunks: list[str] = []
    for match in _TEXT_BLOCK_RE.finditer(svg):
        inner = _CDATA_RE.sub(r"\1", match.group(2))
        text = html.unescape(re.sub(r"<[^>]+>", " ", inner)).strip()
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def _map_tag_bodies(svg: str, mapper) -> str:
    """把 *mapper* 只应用到标签（``<...>``）内部，文本区间原样保留。"""
    parts: list[str] = []
    cursor = 0
    for match in _TAG_RE.finditer(svg):
        parts.append(svg[cursor:match.start()])
        parts.append(mapper(match.group(0)))
        cursor = match.end()
    parts.append(svg[cursor:])
    return "".join(parts)


def _strip_event_and_href_attrs(tag: str) -> str:
    tag = _EVENT_ATTR_RE.sub("", tag)
    return _HREF_ATTR_RE.sub(_drop_external_href, tag)


def _drop_external_href(match: re.Match) -> str:
    """href 白名单只保留文内片段引用（#id），其余（http/file/data/相对路径）整属性移除。"""
    value = match.group(2).strip("\"'")
    if value.startswith("#"):
        return match.group(0)
    return ""


def _check_nesting_depth(svg: str) -> None:
    """粗粒度嵌套深度扫描，防递归下降解析器栈溢出。

    不处理属性值内的 ">" 等边角情况——误判只会造成深度计数偏差，
    精确解析由沙箱内的渲染器负责，超深输入最终仍会被进程边界兜住。
    """
    depth = 0
    max_depth = 0
    index = 0
    length = len(svg)
    while index < length:
        if svg.startswith("<!--", index):
            end = svg.find("-->", index)
            index = length if end < 0 else end + 3
            continue
        char = svg[index]
        if char != "<":
            index += 1
            continue
        if svg.startswith("</", index):
            depth = max(0, depth - 1)
            end = svg.find(">", index)
            index = length if end < 0 else end + 1
            continue
        if index + 1 < length and svg[index + 1] in "?!":
            end = svg.find(">", index)
            index = length if end < 0 else end + 1
            continue
        end = svg.find(">", index)
        if end < 0:
            break
        if not svg[index:end].rstrip().endswith("/"):
            depth += 1
            max_depth = max(max_depth, depth)
        index = end + 1
    if max_depth > MAX_NESTING_DEPTH:
        raise SvgSanitizeError(f"元素嵌套深度超过 {MAX_NESTING_DEPTH}")


def _attr_number(tag: str, name: str) -> float | None:
    """从单个标签里取数值属性；统一处理三种引号形态与科学计数法。"""
    match = re.search(
        rf"""{name}\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", tag, re.IGNORECASE
    )
    if match is None:
        return None
    value = match.group(1).strip("\"'")
    try:
        return float(value.rstrip("%"))
    except ValueError:
        return None


def _check_filter_params(svg: str) -> None:
    """滤镜参数启发式：拦截已知的高消耗组合，错误信息回传模型可自修。

    只扫描标签区间——文本内容里出现 ``numOctaves=99`` 字样属于正常文字，
    不应触发误拒。
    """
    for match in _TAG_RE.finditer(svg):
        tag = match.group(0)
        octaves = _attr_number(tag, "numOctaves")
        if octaves is not None and octaves > MAX_NUM_OCTAVES:
            raise SvgSanitizeError(f"feTurbulence numOctaves 不能超过 {MAX_NUM_OCTAVES:g}")
        deviation = _attr_number(tag, "stdDeviation")
        if deviation is not None and deviation > MAX_STD_DEVIATION:
            raise SvgSanitizeError(f"feGaussianBlur stdDeviation 不能超过 {MAX_STD_DEVIATION:g}")
        frequency = _attr_number(tag, "baseFrequency")
        if frequency is not None and 0 < frequency < MIN_BASE_FREQUENCY:
            raise SvgSanitizeError(f"feTurbulence baseFrequency 不能低于 {MIN_BASE_FREQUENCY}")
        if re.match(r"<filter\b", tag, re.IGNORECASE):
            _check_filter_region(tag)


def _check_filter_region(filter_tag: str) -> None:
    for attr in ("x", "y", "width", "height"):
        value = _attr_number(filter_tag, attr)
        if value is None:
            continue
        if value > MAX_FILTER_REGION_ABS:
            raise SvgSanitizeError(f"filter {attr} 区域不能超过 {MAX_FILTER_REGION_ABS:g}")
    for attr in ("x", "y", "width", "height"):
        raw = re.search(
            rf"""{attr}\s*=\s*["']([\d.]+)%["']""", filter_tag, re.IGNORECASE
        )
        if raw is not None and float(raw.group(1)) > MAX_FILTER_REGION_RATIO * 100:
            raise SvgSanitizeError(f"filter {attr} 区域不能超过 {MAX_FILTER_REGION_RATIO * 100:.0f}%")
