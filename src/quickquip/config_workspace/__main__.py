"""CLI for persistent TOML configuration workspaces."""

import argparse
import json
from pathlib import Path
import sys

from dotenv import load_dotenv
from filelock import Timeout

from quickquip.common.config_writes import ConfigurationBusy
from quickquip.common.paths import PROJECT_ROOT
from quickquip.config_workspace.service import Workspace, validate_offline
from quickquip.llm.config_errors import ConfigError


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, default=PROJECT_ROOT)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("init", "validate", "plan", "pack", "refresh", "status", "resume", "recover"):
        command = commands.add_parser(name)
        command.add_argument("directory", type=Path)
        if name == "plan":
            command.add_argument("--action", choices=("pack", "refresh"), default="pack")
        if name in ("plan", "pack", "refresh"):
            command.add_argument("--overwrite", action="store_true")
        if name in ("pack", "refresh"):
            command.add_argument("--expected-plan", required=True)
        if name in ("pack", "resume", "recover"):
            command.add_argument("--services-stopped", action="store_true")
        if name in ("status", "resume", "recover"):
            command.add_argument("--operation", required=name != "status")
    return result


def execute(args):
    if args.command == "validate":
        return validate_offline(args.directory)
    workspace = Workspace(args.directory, args.root)
    if args.command == "init":
        return workspace.initialize()
    if args.command == "plan":
        return workspace.plan(action=args.action, overwrite=args.overwrite)
    if args.command in ("pack", "refresh"):
        return workspace.execute(
            args.command,
            args.expected_plan,
            overwrite=args.overwrite,
            services_stopped=getattr(args, "services_stopped", False),
        )
    if args.command == "status":
        return workspace.status(args.operation)
    if args.command in ("resume", "recover"):
        return getattr(workspace, args.command)(
            args.operation, services_stopped=args.services_stopped
        )
    raise ConfigError("invalid_command", "Unknown workspace command")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        load_dotenv(args.root / ".env", override=False)
        result = execute(args)
    except (ConfigError, ConfigurationBusy, OSError, Timeout, ValueError) as exc:
        error = (
            exc.as_dict()
            if isinstance(exc, ConfigError)
            else {
                "code": "configuration_busy"
                if isinstance(exc, (ConfigurationBusy, Timeout))
                else "file_error",
                "message": "Workspace operation failed; inspect its status",
                "field_path": "",
                "details": None,
            }
        )
        print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
