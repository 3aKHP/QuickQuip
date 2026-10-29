"""Record the checked-out version and SHA, and choose a safe artifact label."""

import json
import os
from pathlib import Path
import re
import subprocess
import tomllib


def main():
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-(?:dev|rc)\.\d+)?", version):
        raise ValueError("Unexpected project version")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    tag = os.getenv("RELEASE_TAG", "")
    if tag and tag != f"v{version}":
        raise ValueError("Release tag and checked-out project version differ")
    label = tag or f"v{version}-candidate-{sha[:12]}"
    Path("release-identity.json").write_text(
        json.dumps({"version": version, "sha": sha, "tag": tag or None, "label": label}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    if output := os.getenv("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"label={label}\n")
    print(f"{label}: {sha}")


if __name__ == "__main__":
    main()
