"""QuickQuip Admin — native WebView window (Windows only).

Requires ``pywebview`` (installed separately; not in requirements.txt
since it pulls in pythonnet /.NET CLR which is Windows-only).

If pywebview is unavailable this script opens the admin URL in the
default browser and exits with code 2.

The admin address follows ``WEB_ADMIN_HOST`` / ``WEB_ADMIN_PORT`` from the
project ``.env`` (same source as ``web_api.py``); a wildcard bind host
(``0.0.0.0`` / ``::``) is connected via ``127.0.0.1``.
"""

import sys
import time
import urllib.request
import webbrowser

from quickquip.app.web.settings import get_web_admin_host, get_web_admin_port

WAIT_TIMEOUT = 30


def _admin_base_url() -> str:
    host = get_web_admin_host()
    if host in {"0.0.0.0", "::"}:
        # 通配绑定地址不可作为连接目标
        host = "127.0.0.1"
    return f"http://{host}:{get_web_admin_port()}"


def _wait_for_admin(base_url: str) -> None:
    deadline = time.time() + WAIT_TIMEOUT
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base_url}/ops/", timeout=1)
            return
        except Exception:
            time.sleep(1)
    print(f"Warning: admin not ready after {WAIT_TIMEOUT}s", file=sys.stderr)


def main() -> int:
    base_url = _admin_base_url()
    admin_url = f"{base_url}/ops"
    try:
        import webview  # type: ignore[import-untyped]
    except ImportError:
        print("pywebview not installed, falling back to browser", file=sys.stderr)
        _wait_for_admin(base_url)
        webbrowser.open(admin_url)
        return 2

    _wait_for_admin(base_url)
    webview.create_window("QuickQuip Admin", admin_url, width=1280, height=800)
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
