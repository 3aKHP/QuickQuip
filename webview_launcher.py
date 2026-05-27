"""QuickQuip Admin — native WebView window (Windows only).

Requires ``pywebview`` (installed separately; not in requirements.txt
since it pulls in pythonnet /.NET CLR which is Windows-only).

If pywebview is unavailable this script opens the admin URL in the
default browser and exits with code 2.
"""

import sys
import time
import urllib.request
import webbrowser

ADMIN_URL = "http://127.0.0.1:5104/ops"
HEALTH_URL = "http://127.0.0.1:5104/ops/"
WAIT_TIMEOUT = 30


def _wait_for_admin() -> None:
    deadline = time.time() + WAIT_TIMEOUT
    while time.time() < deadline:
        try:
            urllib.request.urlopen(HEALTH_URL, timeout=1)
            return
        except Exception:
            time.sleep(1)
    print(f"Warning: admin not ready after {WAIT_TIMEOUT}s", file=sys.stderr)


def main() -> int:
    try:
        import webview  # type: ignore[import-untyped]
    except ImportError:
        print("pywebview not installed, falling back to browser", file=sys.stderr)
        _wait_for_admin()
        webbrowser.open(ADMIN_URL)
        return 2

    _wait_for_admin()
    webview.create_window("QuickQuip Admin", ADMIN_URL, width=1280, height=800)
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
