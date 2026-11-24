"""Review classification follows the real shared-persistence implementation paths."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/check/deep-cr-trigger.sh"


def _clean_git_env() -> dict[str, str]:
    """Strip inherited GIT_* env vars (e.g. GIT_DIR from worktree hooks)."""
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


@pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt", reason="POSIX Bash gate")
@pytest.mark.parametrize(
    "name,lines,expected",
    [
        ("src/quickquip/configuration/files.py", 350, True),
        ("src/quickquip/configuration/images.py", 350, True),
        ("src/quickquip/configuration/snapshot.py", 350, True),
        ("src/quickquip/llm/config_deployment.py", 350, True),
        ("src/quickquip/configuration/files.py", 2, False),
        ("scripts/deploy/server/remote-deploy-v4.sh", 350, True),
        ("scripts/ops/check_bot.sh", 350, True),
        ("docker/Dockerfile.prod", 350, True),
        ("docs/admin/example.md", 350, False),
    ],
)
def test_shared_persistence_changes_keep_existing_deep_review_thresholds(
    tmp_path, name, lines, expected
):
    env = _clean_git_env()

    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", *args],
            cwd=tmp_path, env=env, text=True, capture_output=True, check=True,
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
        ["bash", str(SCRIPT), base],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    report = json.loads(result.stdout)
    assert report["trigger"] is expected
    if name.startswith("src/quickquip/configuration/"):
        assert any("category_match: touches persistence" in value for value in report["reasons"])


@pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt", reason="POSIX Bash gate")
def test_deep_cr_trigger_ignores_inherited_git_dir(tmp_path, monkeypatch):
    outer = tmp_path / "outer"
    outer.mkdir()
    clean_env = _clean_git_env()

    def outer_git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=Outer", "-c", "user.email=outer@example.test", *args],
            cwd=outer, env=clean_env, text=True, capture_output=True, check=True,
        ).stdout.strip()

    outer_git("init", "--initial-branch", "dev")
    (outer / "README.md").write_text("hello\n", encoding="utf-8")
    outer_git("add", ".")
    outer_git("commit", "-m", "initial")
    outer_head = outer_git("rev-parse", "HEAD")

    monkeypatch.setenv("GIT_DIR", str(outer / ".git"))
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)

    fixture_dir = tmp_path / "fixture"
    fixture_dir.mkdir()
    test_shared_persistence_changes_keep_existing_deep_review_thresholds(
        fixture_dir, "src/quickquip/configuration/files.py", 350, True
    )

    assert outer_git("rev-parse", "HEAD") == outer_head
    assert outer_git("config", "--get", "core.bare") == "false"
