"""SVG→PNG 渲染编排：预检清洗、尺寸推导、沙箱 worker 与渲染限流。

安全模型（详见 ``dev/plans/svg-draw-tool.md``）：
- 输出尺寸永远由服务端从 viewBox 推导后显式传给渲染器，不信任 SVG 自带
  的 width/height 属性（该属性可触发天文数字级位图分配）。
- 渲染始终在 spawn 出的短命子进程内执行：深嵌套段错误、分配失败 abort
  只废 worker 不废 bot 主进程。该进程边界是结构性设计，不受 ``harden``
  开关控制。
- ``harden = True``（默认）时额外启用输入硬约束、静态清洗与 rlimit。
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import threading

from quickquip.common.paths import DATA_DIR
from quickquip.common.rate_limit import KeyedRateLimiter
from quickquip.generation.svg_sanitize import (
    DEFAULT_VIEWBOX_SIZE,
    SvgSanitizeError,
    lenient_viewbox,
    parse_viewbox,
    sanitize_svg,
    strip_root_size_attrs,
)
from quickquip.generation.svg_worker import run_render

logger = logging.getLogger(__name__)

SVG_FONT_PATH = DATA_DIR / "fonts" / "NotoSansSC-Regular.ttf"
SVG_ZOOM = 2
WORKER_AS_LIMIT_BYTES = 2 * 1024**3
WORKER_CPU_SECONDS = 5
WORKER_WALL_TIMEOUT_SECONDS = 8.0
MAX_RENDER_CONCURRENCY = 2

# 渲染是本地 CPU 资源，限流防 prompt injection 驱动的刷图；
# generation 层无法引用 app 层的聊天管线限流器单例，故自持实例
_RENDER_RATE_LIMITER = KeyedRateLimiter(
    {"svg_render": {"global_limit": 10, "user_limit": 2, "scope": "global", "window": 60}}
)
_RENDER_SLOTS = threading.Semaphore(MAX_RENDER_CONCURRENCY)


class SvgRenderError(RuntimeError):
    """渲染 worker 超时、崩溃或报错（原因见消息）。"""


def svg_render_allowed(user_id: int | str, group_id: int | str | None = None) -> bool:
    """SVG 渲染限流入口（全局 10 次/分钟，单用户 2 次/分钟）。"""
    return _RENDER_RATE_LIMITER.allow("svg_render", user_id, group_id=group_id)


async def render_svg_to_png(svg: str, *, harden: bool = True) -> bytes:
    """清洗并在沙箱子进程内渲染 SVG，返回 PNG bytes。

    ``harden=False`` 时跳过输入约束与 rlimit（自担风险的自由选项），
    但尺寸覆盖与子进程边界仍然生效。
    """
    loop = asyncio.get_running_loop()
    with _RENDER_SLOTS:
        return await loop.run_in_executor(None, _render_sync, svg, harden)


def _render_sync(svg: str, harden: bool) -> bytes:
    if harden:
        svg = sanitize_svg(svg)
        width, height = parse_viewbox(svg)
    else:
        width, height = lenient_viewbox(svg) or (DEFAULT_VIEWBOX_SIZE, DEFAULT_VIEWBOX_SIZE)
    svg = strip_root_size_attrs(svg)
    return _run_worker(svg, width * SVG_ZOOM, height * SVG_ZOOM, harden)


def _run_worker(svg: str, width_px: int, height_px: int, harden: bool) -> bytes:
    ctx = mp.get_context("spawn")
    recv, send = ctx.Pipe(duplex=False)
    as_limit = WORKER_AS_LIMIT_BYTES if harden else 0
    cpu_limit = WORKER_CPU_SECONDS if harden else 0
    proc = ctx.Process(
        target=run_render,
        args=(send, svg, str(SVG_FONT_PATH), width_px, height_px, as_limit, cpu_limit),
        daemon=True,
    )
    proc.start()
    try:
        if not recv.poll(WORKER_WALL_TIMEOUT_SECONDS):
            raise SvgRenderError(f"渲染超时（>{WORKER_WALL_TIMEOUT_SECONDS:.0f}s）")
        try:
            kind, payload = recv.recv()
        except (EOFError, OSError):
            raise SvgRenderError(f"渲染器异常退出（exitcode={proc.exitcode}）") from None
        if kind == "ok":
            return payload
        raise SvgRenderError(f"渲染失败：{payload}")
    finally:
        proc.join(timeout=2)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=1)
        send.close()
        recv.close()
        if proc.exitcode not in (0, None):
            logger.warning("SVG 渲染 worker 异常退出：exitcode=%s", proc.exitcode)


__all__ = [
    "SVG_FONT_PATH",
    "SvgRenderError",
    "SvgSanitizeError",
    "render_svg_to_png",
    "sanitize_svg",
    "svg_render_allowed",
]
