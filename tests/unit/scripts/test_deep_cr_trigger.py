"""Review classification follows the real shared-persistence implementation paths."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/check/deep-cr-trigger.sh"


@pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt", reason="POSIX Bash gate")
@pytest.mark.parametrize(
    "name,lines,expected",
    [
        ("src/quickquip/configuration/files.py", 350, True),
        ("src/quickquip/configuration/images.py", 350, True),
        ("src/quickquip/configuration/snapshot.py", 350, True),
        ("src/quickquip/configuration/files.py", 2, False),
        ("docs/admin/example.md", 350, False),
    ],
)
def test_shared_persistence_changes_keep_existing_deep_review_thresholds(
    tmp_path, name, lines, expected
):
    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", *args],
            cwd=tmp_path, text=True, capture_output=True, check=True,
        ).stdout.strip()

    git("init", "--initial-branch", "test-work")
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_text("before\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "baseline")
    base = git("rev-parse", "HEAD")
    path.write_text("".join(f"changed {index}\n" for index in range(lines)), encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "change")
    result = subprocess.run(
        ["bash", str(SCRIPT), base], cwd=tmp_path, text=True, capture_output=True, check=True
    )
    report = json.loads(result.stdout)
    assert report["trigger"] is expected
    if name.startswith("src/quickquip/configuration/"):
        assert any("category_match: touches persistence" in value for value in report["reasons"])
