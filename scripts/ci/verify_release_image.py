"""Bind registry publication to the exact image accepted by the build job."""

import json
from pathlib import Path
import subprocess
import tomllib


def verify_image(accepted, actual, identity, *, sha, version):
    if actual["Id"] != accepted["Id"]:
        raise ValueError("Loaded image differs from the accepted image")
    labels = actual["Config"]["Labels"]
    if identity["sha"] != sha or labels["org.opencontainers.image.revision"] != sha:
        raise ValueError("Accepted image belongs to another commit")
    if identity["version"] != version or labels["org.opencontainers.image.version"] != version:
        raise ValueError("Accepted image version differs from the release")


def main():
    accepted = json.loads(Path("release-image.json").read_text())[0]
    identity = json.loads(Path("release-identity.json").read_text())
    actual = json.loads(subprocess.check_output(["docker", "image", "inspect", "quickquip:smoke"]))[
        0
    ]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    verify_image(accepted, actual, identity, sha=sha, version=version)
    print(f"Accepted image {actual['Id']} matches {sha} / {version}")


if __name__ == "__main__":
    main()
