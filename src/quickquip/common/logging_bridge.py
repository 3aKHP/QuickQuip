"""Bridge stdlib logging into loguru so ``quickquip.*`` INFO logs reach all sinks.

Many modules use stdlib ``logging.getLogger(__name__)``; without this bridge their
records never reach the loguru sinks configured in ``bot.py`` (stdout + file).
"""

from __future__ import annotations

import logging

from loguru import logger

# 逐请求一条 INFO 的高频第三方日志不桥接，避免淹没文件槽
_NOISY_LOGGERS: tuple[str, ...] = ("httpx", "httpcore", "uvicorn.access")


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def install_stdlib_bridge(level: int = logging.INFO) -> None:
    """Route stdlib root logger records into loguru.

    ``level`` 不得低于 INFO：nonebot init 的 DEBUG 配置 dump 含 .env 全部密钥
    （含 API key 与 WEB_ADMIN_PASSWORD），不得进入 loguru 文件槽。
    """
    logging.basicConfig(handlers=[_InterceptHandler()], level=level, force=True)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
