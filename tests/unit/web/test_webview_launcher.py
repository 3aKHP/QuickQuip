"""Admin launcher connection URLs support IPv6 and wildcard bind hosts."""

import pytest

import webview_launcher


@pytest.mark.parametrize(("host", "expected"), [
    ("127.0.0.1", "http://127.0.0.1:55104"),
    ("admin.example.test", "http://admin.example.test:55104"),
    ("::1", "http://[::1]:55104"),
    ("2001:db8::1", "http://[2001:db8::1]:55104"),
    ("[::1]", "http://[::1]:55104"),
    ("0.0.0.0", "http://127.0.0.1:55104"),
    ("::", "http://127.0.0.1:55104"),
    ("[::]", "http://127.0.0.1:55104"),
])
def test_admin_connection_url(monkeypatch, host, expected):
    monkeypatch.setattr(webview_launcher, "get_web_admin_host", lambda: host)
    monkeypatch.setattr(webview_launcher, "get_web_admin_port", lambda: 55104)
    assert webview_launcher._admin_base_url() == expected
