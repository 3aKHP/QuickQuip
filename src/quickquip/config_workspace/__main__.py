"""qqconf: unpack, inspect and pack a local configuration workspace."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from filelock import Timeout

from quickquip.common.config_writes import ConfigurationBusy
from quickquip.configuration.errors import ConfigError
from quickquip.config_workspace.service import Workspace


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("unpack", "refresh", "pack"):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, help="Source QuickQuip project root")
        command.add_argument("--workspace", type=Path, help="Editable configuration directory")
        command.add_argument(
            "--prefer",
            choices=("workspace", "source"),
            help="Select conflicting fields, retaining independent changes",
        )
        command.add_argument("--json", action="store_true", help="Machine-readable output")
        command.add_argument(
            "--show-secrets",
            action="store_true",
            help="Show sensitive preview values in this invocation",
        )
    return result


def execute(args):
    workspace = Workspace(args.workspace, args.root)
    method = getattr(workspace, args.command)
    options = {"prefer": args.prefer}
    if args.command == "refresh":
        options["show_secrets"] = args.show_secrets
    return method(**options)


def _human(result):
    if result["action"] != "refresh":
        print(f"{result['action']}: {result['phase']}")
        if result.get("destination"):
            print(f"Destination: {result['destination']} (services: {result['services']})")
        if result.get("activation"):
            print("Configuration written; deployment activates it.")
        if result.get("workspace"):
            print(f"Workspace: {result['workspace']}")
        return
    if result.get("recovery_required"):
        print(result["message"])
        return
    print(f"Services: {result['services']}; pack destination: {result['destination']}")
    for label in ("workspace_changes", "source_changes", "write_changes"):
        print(f"{label}: {len(result[label])}")
        for change in result[label]:
            if "lines" in change:
                print("\n".join(change["lines"]))
            else:
                before = json.dumps(change["before"], ensure_ascii=False, default=str)
                after = json.dumps(change["after"], ensure_ascii=False, default=str)
                print(f"  {change['field']}: {before} -> {after}")
    for conflict in result["conflicts"]:
        print(f"CONFLICT: {conflict['field']}")
    if result.get("candidate_present"):
        print(
            f"Candidate: pending={result['candidate_pending']}, stale={result['candidate_stale']}"
        )


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        result = execute(args)
    except (ConfigError, ConfigurationBusy, OSError, Timeout, ValueError, sqlite3.Error) as exc:
        error = (
            exc.as_dict()
            if isinstance(exc, ConfigError)
            else {
                "code": "configuration_busy"
                if isinstance(exc, (Timeout, ConfigurationBusy))
                else "file_error",
                "message": "Configuration operation failed; run qqconf refresh",
            }
        )
        if args.json:
            print(json.dumps({"error": error}, ensure_ascii=False, default=str), file=sys.stderr)
        else:
            print(f"{error['code']}: {error['message']}", file=sys.stderr)
            if error.get("field_path"):
                print(error["field_path"], file=sys.stderr)
            for conflict in (error.get("details") or {}).get("conflicts", []):
                print(f"CONFLICT: {conflict['field']}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        _human(result)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
