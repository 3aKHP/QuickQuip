"""SVG→PNG 渲染编排：预检清洗、尺寸推导、沙箱子进程与渲染限流。

安全模型（设计记录见 ``docs/dev/llm-module.md`` 6.5 节）：
- 输出尺寸永远由服务端从 viewBox 推导后显式传给渲染器，不信任 SVG 自带
  的 width/height 属性（该属性可触发天文数字级位图分配）。
- 渲染始终在 ``python -m quickquip.generation.svg_worker`` 短命子进程内执行：
  深嵌套段错误、分配失败 abort 只废 worker 不废 bot 主进程。该进程边界是
  结构性设计，不受 ``harden`` 开关控制。
- ``harden = True``（默认）时额外启用输入硬约束、静态清洗与 rlimit。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import threading
from pathlib import Path

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

logger = logging.getLogger(__name__)

SVG_FONT_PATH = DATA_DIR / "fonts" / "NotoSansSC-Regular.ttf"
SVG_ZOOM = 2
WORKER_AS_LIMIT_BYTES = 2 * 1024**3
WORKER_CPU_SECONDS = 5
WORKER_WALL_TIMEOUT_SECONDS = 8.0
MAX_RENDER_CONCURRENCY = 2
MAX_OUTPUT_PNG_BYTES = 10 * 1024 * 1024

_ERR_PREFIX = b"ERR "
_LENGTH_PREFIX_BYTES = 8

# 渲染是本地 CPU 资源，限流防 prompt injection 驱动的刷图；
# generation 层无法引用 app 层的聊天管线限流器单例，故自持实例。
# 仅在事件循环线程调用（SlidingWindowRateLimiter 非线程安全）。
_RENDER_RATE_LIMITER = KeyedRateLimiter(
    {"svg_render": {"global_limit": 10, "user_limit": 2, "scope": "global", "window": 60}}
)
# 并发闸门只在 executor 线程内获取/释放；若在事件循环线程上阻塞等待，
# 持有者（也在等循环调度续体释放）会与等待者互锁，冻结整个 bot
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
    return await loop.run_in_executor(None, _render_sync, svg, harden)


def _render_sync(svg: str, harden: bool) -> bytes:
    if harden:
        svg = sanitize_svg(svg)
        width, height = parse_viewbox(svg)
    else:
        width, height = lenient_viewbox(svg) or (DEFAULT_VIEWBOX_SIZE, DEFAULT_VIEWBOX_SIZE)
    svg = strip_root_size_attrs(svg)
    with _RENDER_SLOTS:
        png = _run_worker(svg, width * SVG_ZOOM, height * SVG_ZOOM, harden)
    if len(png) > MAX_OUTPUT_PNG_BYTES:
        raise SvgRenderError(f"渲染输出超过 {MAX_OUTPUT_PNG_BYTES // 1024 // 1024}MB 上限")
    return png


def _worker_env() -> dict[str, str]:
    """子进程环境：把 quickquip 包目录兜底加入 PYTHONPATH。

    正常部署（pip 安装）不需要；覆盖未安装的裸源码运行场景，避免
    ``python -m`` 找不到包。
    """
    import os

    env = dict(os.environ)
    package_parent = str(Path(__file__).resolve().parents[2])
    existing = env.get("PYTHONPATH", "")
    parts = [part for part in existing.split(os.pathsep) if part]
    if package_parent not in parts:
        parts.insert(0, package_parent)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _run_worker(svg: str, width_px: int, height_px: int, harden: bool) -> bytes:
    command = [
        sys.executable,
        "-m",
        "quickquip.generation.svg_worker",
        str(SVG_FONT_PATH),
        str(width_px),
        str(height_px),
        str(WORKER_AS_LIMIT_BYTES if harden else 0),
        str(WORKER_CPU_SECONDS if harden else 0),
    ]
    try:
        completed = subprocess.run(
            command,
            input=svg.encode("utf-8"),
            capture_output=True,
            timeout=WORKER_WALL_TIMEOUT_SECONDS,
            env=_worker_env(),
        )
    except subprocess.TimeoutExpired:
        raise SvgRenderError(f"渲染超时（>{WORKER_WALL_TIMEOUT_SECONDS:.0f}s）") from None
    stdout = completed.stdout
    if completed.returncode != 0:
        logger.warning(
            "SVG 渲染 worker 异常退出：exitcode=%s stderr=%s",
            completed.returncode,
            completed.stderr.decode("utf-8", errors="replace")[:200],
        )
        raise SvgRenderError(f"渲染器异常退出（exitcode={completed.returncode}）")
    if stdout.startswith(_ERR_PREFIX):
        message = stdout[len(_ERR_PREFIX):].decode("utf-8", errors="replace").strip()
        raise SvgRenderError(f"渲染失败：{message}")
    if len(stdout) < _LENGTH_PREFIX_BYTES:
        raise SvgRenderError("渲染器输出不完整")
    length = int.from_bytes(stdout[:_LENGTH_PREFIX_BYTES], "big")
    payload = stdout[_LENGTH_PREFIX_BYTES:]
    if len(payload) != length:
        raise SvgRenderError("渲染器输出不完整")
    return payload


__all__ = [
    "SVG_FONT_PATH",
    "SvgRenderError",
    "SvgSanitizeError",
    "render_svg_to_png",
    "sanitize_svg",
    "svg_render_allowed",
]
