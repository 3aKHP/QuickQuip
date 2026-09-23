"""Web Admin 首次导入保持消息管线懒加载。"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_web_app_import_does_not_load_message_pipeline() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3] / "src")
    result = subprocess.run(
        [sys.executable, "-c", (
            "import sys\n"
            "import quickquip.app.web.app\n"
            "assert 'quickquip.app.message_pipeline' not in sys.modules\n"
        )],
        env=env, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
