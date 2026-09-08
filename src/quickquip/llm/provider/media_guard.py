"""内联媒体载荷收口（issue #228）。

单请求内联图片在序列化前统一过 guard：GIF 魔数嗅探后取首帧转 PNG、
MIME 归一、按内容哈希去重、请求级解码字节总量预算。三家协议的消息图、
工具结果图与 MCP 工具图全部经由 ``BaseProviderClient._prepare_image_inputs``
到达这里，改一处全覆盖。

GIF 首帧化的外部依据：Gemini API 拒收 ``image/gif``，OpenAI 仅接受非动图
GIF，Claude/Azure 官方口径为「仅处理首帧」，Kimi 对动图按视频解码计费——
首帧化与最严格 provider 的内部行为一致，无能力损失。
"""
from __future__ import annotations

import hashlib
import logging
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# 单图解码字节上限（沿用既有 5MB 语义：保护内存与下载带宽）。
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# 魔数嗅探优先于声明的 media_type：QQ CDN 的 content-type 不可信，
# 且 MIME 白名单本身含 image/gif（动图体积主力，必须转码）。
_GIF_MAGIC = (b"GIF87a", b"GIF89a")
_DECLARED_PASS_THROUGH = frozenset({"image/png", "image/jpeg", "image/webp"})
_PIL_FORMAT_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}

# 转码结果内容寻址缓存：工具循环逐轮重建请求会对同一批图片反复过 guard，
# 以原始字节哈希为键复用转码结果，避免逐轮重复 Pillow 解码。
# 值为不可变字节，无 TTL；容量对齐 provider 图片下载缓存（32 条）。
_TRANSCODE_CACHE_MAX = 32
_transcode_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()


@dataclass(slots=True)
class GuardedMedia:
    label: str
    data: bytes
    media_type: str
    content_hash: str


def _is_gif(raw: bytes) -> bool:
    return raw.startswith(_GIF_MAGIC)


def _cache_get(key: str) -> tuple[bytes, str] | None:
    hit = _transcode_cache.get(key)
    if hit is not None:
        _transcode_cache.move_to_end(key)
    return hit


def _cache_put(key: str, value: tuple[bytes, str]) -> None:
    _transcode_cache[key] = value
    _transcode_cache.move_to_end(key)
    while len(_transcode_cache) > _TRANSCODE_CACHE_MAX:
        _transcode_cache.popitem(last=False)


def _gif_first_frame_png(raw: bytes) -> bytes | None:
    try:
        # 与 MCP 交付层 _validated_image 同款防炸弹口径：把 Pillow 的
        # DecompressionBombWarning 提升为错误，杜绝超大尺寸头 GIF 在
        # 事件循环上分配巨型帧缓冲（DecompressionBombError 直接继承
        # Exception，必须显式捕获）。
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as img:
                img.seek(0)
                has_alpha = img.info.get("transparency") is not None
                frame = img.convert("RGBA" if has_alpha else "RGB")
                buf = BytesIO()
                frame.save(buf, format="PNG")
                return buf.getvalue()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        logger.warning("media_guard: GIF 首帧提取失败，跳过该图：%s", exc)
        return None


def _sniff_media_type(raw: bytes) -> str | None:
    try:
        with Image.open(BytesIO(raw)) as img:
            return _PIL_FORMAT_MIME.get(img.format or "")
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError):
        return None


def _normalize(label: str, raw: bytes, declared: str) -> tuple[bytes, str] | None:
    """单图归一：GIF 转首帧 PNG；声明缺失/异常时按实际字节嗅探补全。"""
    if not raw:
        logger.warning("media_guard: 跳过空数据的内联媒体 %s（declared=%r）", label, declared)
        return None
    if _is_gif(raw):
        key = hashlib.sha256(raw).hexdigest()
        cached = _cache_get(key)
        if cached is not None:
            return cached
        png = _gif_first_frame_png(raw)
        if png is None:
            return None
        result = (png, "image/png")
        _cache_put(key, result)
        return result
    if declared in _DECLARED_PASS_THROUGH:
        return raw, declared
    sniffed = _sniff_media_type(raw)
    if sniffed is None:
        logger.warning(
            "media_guard: 跳过无法识别的内联媒体 %s（declared=%r, %d bytes）",
            label,
            declared,
            len(raw),
        )
        return None
    return raw, sniffed


def guard_inline_media(
    candidates: list[tuple[str, bytes, str]],
    max_total_bytes: int,
) -> tuple[list[GuardedMedia], list[str]]:
    """对单请求内联媒体做归一、去重与字节预算，返回（保留列表, 丢弃标签）。

    ``candidates`` 为 ``(label, 原始字节, 声明 media_type)``；``max_total_bytes <= 0``
    表示不限总量。同内容只保留首份；单图超过 ``MAX_IMAGE_BYTES`` 整图丢弃。

    预算按优先级前缀止停：候选顺序即重要性顺序（当前消息 → 引用 → 近期），
    第一张装不下的图片连同其后全部丢弃——丢弃当前大图却保留后续无关小图，
    会让模型看到错误 priority 的图片，比看不到更糟。
    """
    kept: list[GuardedMedia] = []
    dropped: list[str] = []
    seen: set[str] = set()
    total = 0
    for index, (label, raw, declared) in enumerate(candidates):
        normalized = _normalize(label, raw, declared)
        if normalized is None:
            dropped.append(label)
            continue
        data, media_type = normalized
        content_hash = hashlib.sha256(data).hexdigest()
        if content_hash in seen:
            logger.info("media_guard: 去重内联媒体 %s（同内容已保留）", label)
            dropped.append(label)
            continue
        if len(data) > MAX_IMAGE_BYTES:
            logger.warning(
                "media_guard: 跳过超限内联媒体 %s（%d bytes > 单图上限 %d）",
                label,
                len(data),
                MAX_IMAGE_BYTES,
            )
            dropped.append(label)
            continue
        if max_total_bytes > 0 and total + len(data) > max_total_bytes:
            remaining = [item[0] for item in candidates[index:]]
            logger.warning(
                "media_guard: 内联媒体超预算，丢弃 %s 及其后 %d 张"
                "（%d bytes，已保留 %d/%d bytes）",
                label,
                len(remaining) - 1,
                len(data),
                total,
                max_total_bytes,
            )
            dropped.extend(remaining)
            break
        seen.add(content_hash)
        total += len(data)
        kept.append(GuardedMedia(label=label, data=data, media_type=media_type, content_hash=content_hash))
    return kept, dropped
