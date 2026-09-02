from __future__ import annotations

import logging

import pytest
from loguru import logger

from quickquip.common.logging_bridge import install_stdlib_bridge


@pytest.fixture()
def captured_logs():
    """Install the stdlib→loguru bridge and capture what loguru receives."""
    install_stdlib_bridge()
    records: list[str] = []
    sink_id = logger.add(lambda msg: records.append(msg), level="DEBUG", format="{message}")
    try:
        yield records
    finally:
        logger.remove(sink_id)
        # 恢复干净的 root logger，避免影响其他测试
        logging.root.handlers.clear()


def test_bridge_forwards_stdlib_info(captured_logs: list[str]):
    logging.getLogger("quickquip.test_probe").info("bridge probe info line")
    assert any("bridge probe info line" in r for r in captured_logs)


def test_bridge_suppresses_debug(captured_logs: list[str]):
    logging.getLogger("quickquip.test_probe").debug("bridge probe debug line")
    assert not any("bridge probe debug line" in r for r in captured_logs)


def test_bridge_suppresses_noisy_third_party(captured_logs: list[str]):
    logging.getLogger("httpx").info('HTTP Request: GET https://example.com "HTTP/1.1 200 OK"')
    assert not any("HTTP Request" in r for r in captured_logs)
