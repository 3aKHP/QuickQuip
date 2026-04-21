from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "extract_release_notes.py"


def _run(cwd: Path, tag: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), tag],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _changelog(body: str) -> str:
    return textwrap.dedent(body).lstrip("\n")


def test_extracts_section_for_tag(tmp_path: Path):
    (tmp_path / "CHANGELOG.md").write_text(
        _changelog(
            """
            # Changelog

            ## [Unreleased]

            - pending

            ## [0.8.1] - 2026-04-15

            ### 新增
            - Feature A
            - Feature B

            ## [0.8.0] - 2026-04-01

            - Older stuff
            """
        ),
        encoding="utf-8",
    )
    result = _run(tmp_path, "v0.8.1")
    assert result.returncode == 0, result.stderr

    notes = (tmp_path / "release_notes.md").read_text(encoding="utf-8")
    assert "Feature A" in notes
    assert "Feature B" in notes
    assert "Older stuff" not in notes
    assert "pending" not in notes


def test_missing_tag_exits_nonzero(tmp_path: Path):
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [0.8.0]\n- x\n", encoding="utf-8")
    result = _run(tmp_path, "v9.9.9")
    assert result.returncode == 1
    assert "No '## [9.9.9]' section" in result.stderr


def test_empty_section_exits_nonzero(tmp_path: Path):
    (tmp_path / "CHANGELOG.md").write_text(
        _changelog(
            """
            # Changelog

            ## [0.8.1]

            ## [0.8.0]
            - x
            """
        ),
        encoding="utf-8",
    )
    result = _run(tmp_path, "v0.8.1")
    assert result.returncode == 1
    assert "is empty" in result.stderr


def test_wrong_argc_prints_usage(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "Usage" in result.stderr
