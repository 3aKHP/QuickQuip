"""Configuration CLI JSON remains readable when redirected on Windows."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("command,exit_code", [("init", 0), ("validate", 1)])
def test_config_cli_emits_utf8_on_legacy_console_encoding(tmp_path, command, exit_code):
    database = tmp_path / "llm_config.db"
    arguments = ["--db", str(database), command]
    if command == "init":
        arguments.extend(["--legacy", str(tmp_path / "missing.toml")])
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3] / "src")
    result = subprocess.run(
        [sys.executable, "-m", "quickquip.llm.config_cli", *arguments],
        cwd=tmp_path, env=env, capture_output=True, timeout=30,
    )
    assert result.returncode == exit_code, result.stderr.decode("utf-8")
    output = (result.stdout if exit_code == 0 else result.stderr).decode("utf-8")
    payload = json.loads(output)
    assert any(ord(character) > 127 for character in output)
    if command == "init":
        assert payload["revision"] == 1
        assert database.is_file()
    else:
        assert payload["error"]["code"] == "not_initialized"
