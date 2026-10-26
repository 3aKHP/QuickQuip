"""Private JSON operations used by qqsync over local processes or authenticated SSH."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import sys

from filelock import Timeout

from quickquip.common.config_writes import ConfigurationBusy, check_writable
from quickquip.config_sync import capture
from quickquip.config_sync.installation import Installation
from quickquip.config_sync.native import Native
from quickquip.configuration.deployment import read as deployment_mode
from quickquip.configuration.errors import ConfigError
from quickquip.configuration.inventory import MAX_TOTAL_BYTES


def execute(root, action, body):
    installation = Installation(root, release=body.get("release"))
    if action == "capture":
        check_writable(installation.root / "data")
        result = capture.read(installation.layout, body.get("source", "draft"))
        result["deployment"] = asdict(deployment_mode(root))
        result["identity"] = installation.state.identity()
        return result
    if action == "native-state":
        return Native(root).inspect()
    if action in ("native-pause", "native-restore", "native-verify"):
        method = getattr(Native(root), action.removeprefix("native-"))
        method(body["original"])
        return {"phase": action}
    if action == "prepare":
        deployment_mode(root, required=True)
        expected = {
            key: value
            for key, value in body["expected"].items()
            if key not in ("deployment", "identity")
        }
        return installation.prepare(
            body["operation"],
            expected,
            body["target"],
            publish=body["publish"],
            prefer=body.get("prefer"),
        )
    if action == "inspect":
        record = installation.read(body["operation"])
        return {**installation.summary(record), "deployment": record.get("deployment")}
    if action in ("install", "restore"):
        options = {"environment": body.get("environment")}
        if action == "install":
            options["hot"] = body.get("hot", False)
        return getattr(installation, action)(body["operation"], **options)
    if action in ("verify", "recovered"):
        return getattr(installation, action)(body["operation"], running=body.get("running", False))
    if action == "confirm":
        return installation.confirm(body["operation"])
    raise ConfigError("invalid_command", "Unknown configuration operation")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action")
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.read(MAX_TOTAL_BYTES * 8 + 1)
        if len(raw) > MAX_TOTAL_BYTES * 8:
            raise ConfigError("body_too_large", "Configuration operation exceeds its limit")
        body = json.loads(raw or "{}")
        result = execute(args.root, args.action, body)
    except (
        ConfigError,
        ConfigurationBusy,
        OSError,
        ValueError,
        KeyError,
        sqlite3.Error,
        Timeout,
    ) as exc:
        result = {
            "error": exc.as_dict()
            if isinstance(exc, ConfigError)
            else {
                "code": "configuration_busy"
                if isinstance(exc, (ConfigurationBusy, Timeout))
                else "configuration_failed",
                "message": "Configuration operation failed; repeat qqsync to resume",
            }
        }
    print(json.dumps(result, ensure_ascii=False))
    # The JSON envelope carries domain failures; the transport retains process failures separately.
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
