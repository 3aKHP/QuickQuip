"""resvg 渲染 worker：以 ``python -m`` 独立子进程执行受限渲染。

以 ``python -m quickquip.generation.svg_worker`` 方式调用（不经
multiprocessing spawn，避免子进程重新导入应用入口 bot.py 的全部
模块级副作用）。协议：

- argv：font_path width_px height_px as_limit_bytes cpu_seconds
- stdin：完整 SVG 文本（读到 EOF）
- stdout：成功 = 8 字节大端长度 + PNG bytes；失败 = ``ERR `` 前缀 + 一行错误
- rlimit 在导入 resvg 之前生效；任何崩溃（段错误 / 分配失败 abort）由
  父进程按退出码归类，进程边界兜住。
"""

from __future__ import annotations

import os
import sys

_LENGTH_PREFIX_BYTES = 8


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


def main() -> int:
    if len(sys.argv) != 6:
        sys.stdout.write("ERR usage: svg_worker font_path width height as_limit cpu_limit\n")
        return 0
    font_path, width_arg, height_arg, as_limit_arg, cpu_limit_arg = sys.argv[1:]
    # rlimit 必须先于 resvg 导入生效——导入阶段就可能发生大额分配
    _apply_limits(int(as_limit_arg), int(cpu_limit_arg))
    svg = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        import resvg_py

        font_files = [font_path] if font_path and os.path.exists(font_path) else []
        png = resvg_py.svg_to_bytes(
            svg_string=svg,
            font_files=font_files,
            width=int(width_arg),
            height=int(height_arg),
        )
        sys.stdout.buffer.write(len(png).to_bytes(_LENGTH_PREFIX_BYTES, "big"))
        sys.stdout.buffer.write(png)
        sys.stdout.buffer.flush()
    except BaseException as exc:  # noqa: BLE001 — worker 侧任何异常都只上报不外抛
        sys.stdout.write(f"ERR {type(exc).__name__}: {exc}\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
