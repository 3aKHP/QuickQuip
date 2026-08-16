"""resvg 渲染 worker：在独立子进程内执行受限渲染。

本模块被 ``svg.py`` 以 spawn 方式启动。子进程内发生的一切（段错误、
Rust 分配失败 abort、CPU 打满）都由进程边界与 rlimit 兜住，不影响 bot
主进程。结果经单向管道回传 ``("ok", png_bytes)`` 或 ``("error", message)``；
子进程在写入前崩溃时管道保持为空，由父进程按墙钟超时归类。

本模块必须保持导入无副作用（spawn 会在子进程内重新 import）。
"""

from __future__ import annotations

import os


def _apply_limits(as_limit_bytes: int, cpu_seconds: int) -> None:
    """在导入 resvg 之前应用 rlimit；非 POSIX 平台无对应机制，静默跳过。"""
    if as_limit_bytes <= 0 or cpu_seconds <= 0:
        return
    try:
        import resource
    except ImportError:
        return
    resource.setrlimit(resource.RLIMIT_AS, (as_limit_bytes, as_limit_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))


def run_render(
    send_pipe,
    svg: str,
    font_path: str,
    width_px: int,
    height_px: int,
    as_limit_bytes: int,
    cpu_seconds: int,
) -> None:
    """worker 入口：受限渲染单张 SVG 并把 PNG bytes 写回管道。"""
    # rlimit 必须先于 resvg 导入生效——导入阶段就可能发生大额分配
    _apply_limits(as_limit_bytes, cpu_seconds)
    try:
        import resvg_py

        font_files = [font_path] if font_path and os.path.exists(font_path) else []
        png = resvg_py.svg_to_bytes(
            svg_string=svg,
            font_files=font_files,
            width=width_px,
            height=height_px,
        )
        send_pipe.send(("ok", png))
    except BaseException as exc:  # noqa: BLE001 — worker 侧任何异常都只上报不外抛
        send_pipe.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        send_pipe.close()
