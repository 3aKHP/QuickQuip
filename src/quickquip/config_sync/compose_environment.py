"""Resolve a candidate's Compose environment on its host without changing real files."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def resolve(description, files):
    root, application = Path(description["root"]), Path(description["application"])
    compose = Path(description["compose"])
    with tempfile.TemporaryDirectory(prefix="qqsync-compose-") as directory:
        staging = Path(directory)
        # Materialize the Compose inputs; other managed files are irrelevant to interpolation.
        names = [".env", str(compose.relative_to(application))]
        names.extend(str(Path(path).relative_to(application)) for path in description["overrides"])
        for name in names:
            if name not in files:
                raise ValueError("Candidate is missing its Compose file or root environment")
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(files[name]["content"], validate=True))
            path.chmod(0o600)
        staged_compose = staging / compose.relative_to(application)
        command = [
            "docker",
            "compose",
            "--env-file",
            str(staging / ".env"),
            "-f",
            str(staged_compose),
        ]
        for override in description["overrides"]:
            command.extend(["-f", str(staging / Path(override).relative_to(application))])
        environment = {
            **os.environ,
            "QUICKQUIP_ROOT": str(root),
            "QUICKQUIP_ENV_FILE": str(staging / ".env"),
        }
        if root != application:
            environment["QUICKQUIP_RELEASE"] = application.name
        result = subprocess.run(
            [*command, "config", "--format", "json"],
            cwd=staged_compose.parent,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        if result.returncode:
            raise ValueError("Candidate Compose validation failed")
        services = json.loads(result.stdout)["services"]
        if "web-admin" not in services:
            raise ValueError("Configuration helper requires the web-admin service")
        return {
            "environment": services["quickquip"].get("environment", {}),
            "services": list(services),
        }


if __name__ == "__main__":
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(resolve(payload["description"], payload["files"])))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print(
            '{"error":{"code":"invalid_compose","message":"Candidate Compose validation failed"}}'
        )
