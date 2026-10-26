"""Configuration stages inside deploy-v4's existing release transaction."""

import argparse
import json
from pathlib import Path
import re
import sys

from quickquip.config_sync.installation import Installation
from quickquip.config_sync.host_files import return_ownership
from quickquip.config_sync.layout import Layout
from quickquip.configuration.errors import ConfigError
from quickquip.configuration.inventory import body
from quickquip.llm.config_durability import durable_write


def execute(root, application_release, action, operation, release=None):
    installation = Installation(root, release=application_release)
    if action == "bind-deployment":
        if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-f0-9]{12}", release or ""):
            raise ConfigError("invalid_field", "Invalid deployment release")
        with installation.owned(operation) as record:
            if record.get("deployment") not in (None, release):
                raise ConfigError(
                    "deployment_changed", "Configuration belongs to another deployment"
                )
            record["deployment"] = release
            installation.save(record)
            environment = record["target"]["files"].get(".env")
            if environment is None:
                raise ConfigError("missing_environment", "Deployment requires root .env")
            staged = installation.root / ".deploy/incoming" / release / "shared/.env"
            durable_write(staged, body(environment))
            staged.chmod(environment["mode"])
            return_ownership(staged)
            return installation.summary(record)
    if action == "stage":
        with installation.owned(operation) as record:
            if record["phase"] not in ("prepared", "staged"):
                raise ConfigError("operation_conflict", "Configuration is already installing")
            if record.get("deployment") != release:
                raise ConfigError("deployment_changed", "Candidate differs from bound deployment")
            candidate = Layout(root, release=release)
            before = {
                name: value
                for name, value in candidate.read_files().items()
                if candidate.owner(name) == candidate.application
            }
            target = {
                name: value
                for name, value in record["target"]["files"].items()
                if candidate.owner(name) == candidate.application
            }
            candidate.install(before, target)
            record["phase"] = "staged"
            installation.save(record)
            return installation.summary(record)
    if action == "candidate-commit":
        return installation.install(operation)
    if action in ("wait", "verify-committed"):
        return installation.verify(operation, running=True)
    if action == "recover":
        return installation.restore(operation)
    if action == "recovery-verified":
        return installation.recovered(operation, running=True)
    if action == "inspect":
        record = installation.read(operation)
        return {**installation.summary(record), "deployment": record.get("deployment")}
    raise ConfigError("invalid_command", "Unknown deployment configuration stage")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--application-release", required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--release")
    parser.add_argument("--services-stopped", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = execute(
            args.root, args.application_release, args.action, args.operation, args.release
        )
    except (ConfigError, OSError, ValueError, KeyError) as exc:
        error = (
            exc.as_dict()
            if isinstance(exc, ConfigError)
            else {
                "code": "deployment_configuration_failed",
                "message": "Configuration stage failed",
            }
        )
        print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
