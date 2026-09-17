"""内联媒体载荷收口（issue #228）。

单请求内联图片在序列化前统一过 guard：GIF 魔数嗅探后取首帧转 PNG、
MIME 归一、按内容哈希去重、请求级解码字节总量预算、超限媒体降采样
重编码适配。三家协议的消息图、工具结果图与 MCP 工具图全部经由
``BaseProviderClient._prepare_image_inputs`` 到达这里，改一处全覆盖。

GIF 首帧化的外部依据：Gemini API 拒收 ``image/gif``，OpenAI 仅接受非动图
GIF，Claude/Azure 官方口径为「仅处理首帧」，Kimi 对动图按视频解码计费——
首帧化与最严格 provider 的内部行为一致，无能力损失。
"""

from __future__ import annotations

import hashlib
import logging
import threading
import warnings
from collections import OrderedDict
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

# 单图解码字节上限：URL 图在下载层即按此拒绝（保护内存与下载带宽）；
# 内联/MCP/GIF 转码路径到达这里的超限媒体先降采样重编码到该上限内，
# 压缩未达标才丢弃。
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# 魔数嗅探优先于声明的 media_type：QQ CDN 的 content-type 不可信，
# 且 MIME 白名单本身含 image/gif（动图体积主力，必须转码）。
_GIF_MAGIC = (b"GIF87a", b"GIF89a")
_DECLARED_PASS_THROUGH = frozenset({"image/png", "image/jpeg", "image/webp"})
_PIL_FORMAT_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}

# 转码结果内容寻址缓存：工具循环逐轮重建请求会对同一批图片反复过 guard，
# 以原始字节哈希为键复用转码结果，避免逐轮重复 Pillow 解码。
# 值为不可变字节，无 TTL；容量对齐 provider 图片下载缓存（32 条）。
# 设计假设：GIF 首帧 PNG 只由原始字节决定，与调用方 provider/预算无关——
# 若未来需要按 provider 差异化转码策略，此缓存必须先行键扩展。
_TRANSCODE_CACHE_MAX = 32
_transcode_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()

# 超限适配（降采样重编码）：原始尺寸优先、长边阶梯次之，两档 JPEG 质量
# 逐级尝试，命中目标额度即停——照片与截图在第一档通常已达标，保真损耗
# 最小。压缩结果按（原始字节哈希, 目标额度）缓存：额度随请求组装变化，
# 键必须含目标额度才不影响 GIF 转码缓存的「与预算无关」假设。
_COMPRESS_QUALITY_STEPS = (85, 70)
_COMPRESS_LONG_EDGE_STEPS = (2560, 2048, 1600, 1280, 1024, 768)
_COMPRESS_TARGET_FLOOR_BYTES = 96 * 1024
_COMPRESS_CACHE_MAX = 32
_compress_cache: OrderedDict[tuple[str, int], tuple[bytes, str]] = OrderedDict()

# guard 主体经 asyncio.to_thread 下沉到工作线程执行（Pillow 解码/重编码
# 病态路径可达秒级，不能占住事件循环）；两个模块级 LRU 的复合操作
# （写入 + move_to_end + 淘汰）非原子，跨线程并发须持锁。
_CACHE_LOCK = threading.Lock()


@dataclass(slots=True)
class GuardedMedia:
    label: str
    data: bytes
    media_type: str
    content_hash: str


def _is_gif(raw: bytes) -> bool:
    return raw.startswith(_GIF_MAGIC)


def _cache_get(key: str) -> tuple[bytes, str] | None:
    with _CACHE_LOCK:
        hit = _transcode_cache.get(key)
        if hit is not None:
            _transcode_cache.move_to_end(key)
        return hit


def _cache_put(key: str, value: tuple[bytes, str]) -> None:
    with _CACHE_LOCK:
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


def _compress_cache_get(key: tuple[str, int]) -> tuple[bytes, str] | None:
    with _CACHE_LOCK:
        hit = _compress_cache.get(key)
        if hit is not None:
            _compress_cache.move_to_end(key)
        return hit


def _compress_cache_put(key: tuple[str, int], value: tuple[bytes, str]) -> None:
    with _CACHE_LOCK:
        _compress_cache[key] = value
        _compress_cache.move_to_end(key)
        while len(_compress_cache) > _COMPRESS_CACHE_MAX:
            _compress_cache.popitem(last=False)


def _compress_bytes(raw: bytes, media_type: str, target_bytes: int) -> tuple[bytes, str] | None:
    """把超限媒体压进目标额度；无法达成时返回 ``None``。

    EXIF 方向先校正（手机照片普遍依赖 EXIF 旋转），透明通道平铺到白底
    （内联图仅供模型查看，不回传用户，JPEG 无损透明无必要）。解码、缩放
    与重编码全程在同一异常口径内：任一环节失败按「压缩未达标」走丢弃，
    不得让单张病态图（如极端长宽比）炸掉整个请求组装。
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as img:
                img.load()
                has_alpha = img.mode in ("RGBA", "LA") or img.info.get("transparency") is not None
                base = ImageOps.exif_transpose(img).convert("RGBA" if has_alpha else "RGB")
        if base.mode == "RGBA":
            background = Image.new("RGB", base.size, (255, 255, 255))
            background.paste(base, mask=base.getchannel("A"))
            base = background
        long_edge = max(base.size)
        for edge in (None, *_COMPRESS_LONG_EDGE_STEPS):
            if edge is not None and edge >= long_edge:
                continue
            if edge is None:
                frame = base
            else:
                # 极端长宽比下短边按比例会取整到 0，钳制为 1 保住有效位图。
                scale = edge / long_edge
                frame = base.resize(
                    (
                        max(1, round(base.width * scale)),
                        max(1, round(base.height * scale)),
                    ),
                    Image.Resampling.LANCZOS,
                )
            for quality in _COMPRESS_QUALITY_STEPS:
                buf = BytesIO()
                frame.save(buf, format="JPEG", quality=quality)
                if buf.tell() <= target_bytes:
                    return buf.getvalue(), "image/jpeg"
        return None
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        logger.warning(
            "media_guard: 超限媒体降采样重编码失败，放弃压缩（declared=%r, %d bytes）：%s",
            media_type,
            len(raw),
            exc,
        )
        return None


def _compress_to_fit(raw: bytes, media_type: str, target_bytes: int) -> tuple[bytes, str] | None:
    """缓存版超限适配入口；额度低于压缩下限时直接放弃。"""
    if target_bytes < _COMPRESS_TARGET_FLOOR_BYTES:
        return None
    key = (hashlib.sha256(raw).hexdigest(), target_bytes)
    cached = _compress_cache_get(key)
    if cached is not None:
        return cached
    result = _compress_bytes(raw, media_type, target_bytes)
    if result is not None:
        _compress_cache_put(key, result)
    return result


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


@dataclass
class InlineMediaBudget:
    """一次请求组装的媒体预算，按优先级接收多批候选。

    由请求组装函数创建并显式传递；跨消息共享去重和前缀止停状态。
    max_total_bytes <= 0 表示不限字节，内容去重和单图限制持续生效。
    """

    max_total_bytes: int
    total: int = field(default=0, init=False)
    exhausted: bool = field(default=False, init=False)
    _seen: set[str] = field(default_factory=set, init=False, repr=False)

    def guard(
        self, candidates: list[tuple[str, bytes, str]]
    ) -> tuple[list[GuardedMedia], list[str]]:
        kept: list[GuardedMedia] = []
        dropped: list[str] = []
        for index, (label, raw, declared) in enumerate(candidates):
            if self.exhausted:
                dropped.extend(item[0] for item in candidates[index:])
                break
            normalized = _normalize(label, raw, declared)
            if normalized is None:
                dropped.append(label)
                continue
            data, media_type = normalized
            # 超限先压缩再丢弃：大尺寸截图/扫描件降采样重编码后常规额度即可
            # 容纳；静默丢弃会让模型对着「[附图 N 张]」标记盲猜（2026-09 生产事故）。
            if len(data) > MAX_IMAGE_BYTES:
                fitted = _compress_to_fit(data, media_type, MAX_IMAGE_BYTES)
                if fitted is None:
                    logger.warning(
                        "media_guard: 跳过超限内联媒体 %s（%d bytes > 单图上限 %d，压缩未达标）",
                        label,
                        len(data),
                        MAX_IMAGE_BYTES,
                    )
                    dropped.append(label)
                    continue
                data, media_type = fitted
            if self.max_total_bytes > 0 and self.total + len(data) > self.max_total_bytes:
                fitted = _compress_to_fit(data, media_type, self.max_total_bytes - self.total)
                if fitted is None:
                    logger.warning(
                        "media_guard: 内联媒体超预算，丢弃 %s 及后续低优先级图片"
                        "（%d bytes，已保留 %d/%d bytes）",
                        label,
                        len(data),
                        self.total,
                        self.max_total_bytes,
                    )
                    self.exhausted = True
                    dropped.extend(item[0] for item in candidates[index:])
                    break
                data, media_type = fitted
            content_hash = hashlib.sha256(data).hexdigest()
            if content_hash in self._seen:
                logger.info("media_guard: 去重内联媒体 %s（同内容已保留）", label)
                dropped.append(label)
                continue
            self._seen.add(content_hash)
            self.total += len(data)
            kept.append(
                GuardedMedia(
                    label=label, data=data, media_type=media_type, content_hash=content_hash
                )
            )
        return kept, dropped


def guard_inline_media(
    candidates: list[tuple[str, bytes, str]],
    max_total_bytes: int,
) -> tuple[list[GuardedMedia], list[str]]:
    """归一、去重并限制一批媒体；多批请求通过 InlineMediaBudget 共享额度。"""
    return InlineMediaBudget(max_total_bytes).guard(candidates)
