from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "validate_toml_examples.py"


def _run(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_valid_examples_passes(tmp_path: Path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "chat_rules.toml.example").write_text('title = "hi"\n', encoding="utf-8")

    personas = config / "personas.example"
    personas.mkdir()
    (personas / "default.toml").write_text('name = "default"\n', encoding="utf-8")

    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "OK (2 files)" in result.stdout


def test_invalid_toml_fails(tmp_path: Path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "broken.toml.example").write_text("not = valid = toml\n", encoding="utf-8")
    (tmp_path / "config" / "personas.example").mkdir()

    result = _run(tmp_path)
    assert result.returncode == 1
    assert "FAIL" in result.stderr


def test_missing_config_dirs_yields_zero_files(tmp_path: Path):
    # With no matching files, the script should still succeed.
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "OK (0 files)" in result.stdout
