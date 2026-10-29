"""Verify an isolated extracted package or image against actual v1.16.3 sources.

The installation directory must be disposable. No credentials or external services
are used. Reports and service logs remain in its data directory for CI artifacts.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import uuid


def clean_environment():
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def stop_tree(process):
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=30,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGINT)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
    finally:
        if os.name != "nt":
            # A runner can exit before its descendants release inherited pipes.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def run_stage(command, *, root, log_path, container=None, timeout=240):
    options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    process = subprocess.Popen(
        command,
        cwd=root,
        env=clean_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **options,
    )
    output = ""
    try:
        output, _ = process.communicate(timeout=timeout)
        return process.returncode
    except BaseException:
        stop_tree(process)
        output, _ = process.communicate(timeout=10)
        raise
    finally:
        log_path.write_text(output or "", encoding="utf-8")
        print(output or "", end="", flush=True)
        if container:
            cleanup = subprocess.run(
                ["docker", "rm", "--force", container],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if cleanup.returncode and "No such container" not in cleanup.stderr:
                raise RuntimeError(f"Could not remove acceptance container {container}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--image", help="Use docker run instead of a native Python")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    root, baseline = args.installation.resolve(), args.baseline.resolve()
    if not (baseline / "src/quickquip/llm/config_store.py").is_file():
        parser.error("baseline must contain the extracted v1.16.3 source tree")
    if root == repository or (
        (root / ".env").exists() or ((root / "data").exists() and any((root / "data").iterdir()))
    ):
        parser.error("installation must be disposable with no .env or data directory")
    for name in ("config", "data"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / ".env").write_text(
        "QUICKQUIP_DEPLOY_LOCATION=local\nQUICKQUIP_DEPLOY_RUNTIME=source\n"
        "WEB_ADMIN_PASSWORD=synthetic-release-only\nTIEBA_ENABLED=false\n"
        "DRIVER=~fastapi+~websockets\nONEBOT_WS_URLS=[]\n",
        encoding="utf-8",
    )
    scenario = repository / "tests/release/storage_scenario.py"
    completed = []
    for stage in (
        "seed",
        "upgrade",
        "reverse",
        "old_read",
        "reupgrade",
        "business_seed",
        "business_upgrade",
        "live",
    ):
        old = stage in ("seed", "old_read", "business_seed")
        script = scenario if stage != "live" else scenario.with_name("live_candidate.py")
        container = "quickquip-upgrade-" + uuid.uuid4().hex if args.image else None
        if args.image:
            command = [
                "docker",
                "run",
                "--rm",
                "--name",
                container,
                "--network",
                "none",
                "-e",
                "QUICKQUIP_MANAGED_CONTAINER=1",
                "-v",
                f"{baseline}:/baseline:ro",
                "-v",
                f"{script}:/verify.py:ro",
                "-v",
                f"{root / 'config'}:/app/config",
                "-v",
                f"{root / 'data'}:/app/data",
                "-v",
                f"{root / '.env'}:/app/.env:ro",
                # Expected values and migration results belong to the shared data directory.
                args.image,
                "python",
                "/verify.py",
                *([stage] if stage != "live" else []),
                "/app",
                "/baseline/src" if old else "/app/src",
            ]
        else:
            source = (
                baseline / "src" if old else (root / "src" if (root / "src").is_dir() else root)
            )
            command = [
                str(Path(args.python).absolute()),
                str(script),
                *([stage] if stage != "live" else []),
                str(root),
                str(source),
            ]
        code = run_stage(
            command,
            root=root,
            log_path=root / "data" / f"release-{stage}.log",
            container=container,
        )
        if code:
            raise SystemExit(code)
        completed.append(stage)
    report = {"baseline": "v1.16.3", "stages": completed, "result": "passed"}
    (root / "data/release-upgrade.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
