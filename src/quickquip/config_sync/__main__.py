"""qqsync: preview, push and pull real project configuration."""

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from filelock import Timeout

from quickquip.common.config_writes import ConfigurationBusy
from quickquip.common.env import PROJECT_ROOT
from quickquip.config_sync.session import Session, public_preview
from quickquip.configuration.errors import ConfigError


def parser():
    result = argparse.ArgumentParser(prog="qqsync", description=__doc__)
    commands = result.add_subparsers(dest="command")
    for name in ("refresh", "push", "pull"):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, default=PROJECT_ROOT)
        command.add_argument("--json", action="store_true")
        selection = command.add_mutually_exclusive_group()
        selection.add_argument("--prefer", choices=("source", "target"))
        selection.add_argument("--overwrite", action="store_true")
        if name == "refresh":
            command.add_argument("--direction", choices=("push", "pull"), default="push")
            command.add_argument("--show-secrets", action="store_true")
        if name in ("refresh", "pull"):
            command.add_argument("--source", choices=("published", "draft"), default="published")
    return result


def human(result):
    print(result.get("message", "qqsync: " + result["phase"]))
    for change in result.get("write_changes", []):
        if "lines" in change:
            print("\n".join(change["lines"]))
        else:
            print(
                f"  {change['field']}: {json.dumps(change['before'], ensure_ascii=False)}"
                f" -> {json.dumps(change['after'], ensure_ascii=False)}"
            )
    for conflict in result.get("conflicts", []):
        print("CONFLICT: " + conflict["field"])
    if result.get("target_changes"):
        print(f"Receiver changes: {len(result['target_changes'])}")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    cli = parser()
    args = cli.parse_args(argv)
    if args.command is None:
        cli.print_help()
        return 0
    try:
        session = Session(args.root)
        options = {
            "source": getattr(args, "source", "published"),
            "prefer": args.prefer,
            "overwrite": args.overwrite,
        }
        if args.command == "refresh":
            if args.source == "draft" and args.direction != "pull":
                raise ConfigError("invalid_field", "--source draft requires --direction pull")
            result = public_preview(
                session.preview(args.direction, show_secrets=args.show_secrets, **options)
            )
        else:
            result = session.run(args.command, **options)
    except (
        ConfigError,
        ConfigurationBusy,
        OSError,
        ValueError,
        sqlite3.Error,
        Timeout,
        subprocess.SubprocessError,
    ) as exc:
        error = (
            exc.as_dict()
            if isinstance(exc, ConfigError)
            else {
                "code": "configuration_busy"
                if isinstance(exc, (ConfigurationBusy, Timeout))
                else "configuration_failed",
                "message": "Configuration operation failed; repeat the same qqsync command",
            }
        )
        if args.json:
            print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"{error['code']}: {error['message']}", file=sys.stderr)
            for conflict in (error.get("details") or {}).get("conflicts", []):
                print("CONFLICT: " + conflict["field"], file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        human(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
