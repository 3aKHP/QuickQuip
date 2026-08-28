"""app.web.settings 的 WEB_ADMIN_HOST/PORT getter 测试（PR #145）。"""

from __future__ import annotations

import pytest

from quickquip.app.web import settings


@pytest.fixture(autouse=True)
def _no_env_load(monkeypatch):
    """getter 内的 load_web_env 会读真实根目录 .env，测试环境改为 no-op 保持 hermetic。"""
    monkeypatch.setattr(settings, "load_web_env", lambda: None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 5104),       # 未设置
        ("", 5104),         # 空串
        ("  ", 5104),       # 空白
        ("abc", 5104),      # 非数字回退默认
        ("-5", 1),          # 收敛到下界
        ("0", 1),
        ("99999", 65535),   # 收敛到上界
        ("5104", 5104),
        ("55104", 55104),
    ],
)
def test_get_web_admin_port(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("WEB_ADMIN_PORT", raising=False)
    else:
        monkeypatch.setenv("WEB_ADMIN_PORT", raw)
    assert settings.get_web_admin_port() == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "127.0.0.1"),
        ("", "127.0.0.1"),
        ("  ", "127.0.0.1"),
        ("0.0.0.0", "0.0.0.0"),  # 通配绑定地址原样返回；连接侧回退由 webview_launcher 负责
        ("192.168.1.2", "192.168.1.2"),
    ],
)
def test_get_web_admin_host(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("WEB_ADMIN_HOST", raising=False)
    else:
        monkeypatch.setenv("WEB_ADMIN_HOST", raw)
    assert settings.get_web_admin_host() == expected
