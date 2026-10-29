"""Release failures release resources; publication rejects substituted artifacts."""

import importlib.util
from pathlib import Path
import subprocess
import sys

from filelock import FileLock
import pytest


def load_script(name):
    path = Path(__file__).resolve().parents[3] / "scripts/ci" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acceptance_timeout_reaps_descendant_and_keeps_output(tmp_path):
    runner = load_script("verify_release_upgrade")
    child = (
        "from filelock import FileLock; from pathlib import Path; import time; "
        "lock=FileLock('child.lock'); lock.acquire(); "
        "Path('ready').touch(); print('child ready',flush=True); time.sleep(120)"
    )
    parent = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
        "exec(\"while not Path('ready').exists(): time.sleep(0.01)\"); "
        "print('stage ready',flush=True); time.sleep(120)"
    )
    log = tmp_path / "stage.log"
    with pytest.raises(subprocess.TimeoutExpired):
        runner.run_stage([sys.executable, "-c", parent], root=tmp_path, log_path=log, timeout=3)
    assert "stage ready" in log.read_text()
    # The descendant held this lock while alive; its release observes OS resource cleanup.
    with FileLock(tmp_path / "child.lock", timeout=5):
        pass


@pytest.mark.parametrize("changed", ["image", "revision", "version", "identity"])
def test_publication_rejects_unaccepted_image(changed):
    verifier = load_script("verify_release_image")
    image = {
        "Id": "sha256:accepted",
        "Config": {
            "Labels": {
                "org.opencontainers.image.revision": "accepted-sha",
                "org.opencontainers.image.version": "1.16.4",
            }
        },
    }
    identity = {"sha": "accepted-sha", "version": "1.16.4"}
    verifier.verify_image(image, image, identity, sha="accepted-sha", version="1.16.4")
    if changed == "image":
        image["Id"] = "sha256:substituted"
    elif changed == "identity":
        identity["sha"] = "another-commit"
    else:
        image["Config"]["Labels"]["org.opencontainers.image." + changed] = "other"
    with pytest.raises(ValueError):
        verifier.verify_image(
            {"Id": "sha256:accepted"}, image, identity, sha="accepted-sha", version="1.16.4"
        )
