"""Local SSH configuration synchronization driver."""

import argparse
import json
from pathlib import Path
import sys

from quickquip.common.config_writes import ConfigurationBusy
from quickquip.common.env import PROJECT_ROOT, load_root_env_file
from quickquip.config_sync.client import Synchronizer
from quickquip.config_sync.endpoint import Endpoint
from quickquip.config_sync.state import identifier
from quickquip.config_sync.transport import SSHRemote
from quickquip.llm.config_errors import ConfigError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        nargs="?",
        default="sync",
        choices=(
            "sync",
            "init",
            "status",
            "resume",
            "recover",
            "deploy-prepare",
            "deploy-finish",
        ),
    )
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--host-alias", default="quickquip-prod")
    parser.add_argument("--remote-dir", default="/opt/QuickQuip")
    parser.add_argument("--mode", choices=("auto", "push", "pull"), default="auto")
    parser.add_argument("--from", dest="initial", choices=("local", "remote"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--operation")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args(argv)
    load_root_env_file()
    try:
        if args.action == "init" and args.initial is None:
            raise ConfigError("missing_source", "Initialization requires --from local or remote")
        if args.initial and args.action != "init":
            raise ConfigError("invalid_field", "--from is only valid for initialization")
        if args.plan and args.action not in ("sync", "init", "deploy-prepare"):
            raise ConfigError("invalid_field", "--plan is only valid for synchronization planning")
        if args.action in ("resume", "recover", "deploy-finish"):
            identifier(args.operation)
        if args.overwrite and args.action != "init" and args.mode == "auto":
            raise ConfigError("invalid_field", "Overwrite requires push or pull")
        local = Endpoint(args.root)
        if args.timeout <= 0:
            raise ConfigError("invalid_field", "Timeout must be positive")
        if args.action == "init" and not args.plan and not local.service.path.exists():
            local.service.initialize()
        remote = SSHRemote(args.host_alias, args.remote_dir)
        sync = Synchronizer(local, remote)
        if args.action == "status":
            result = {
                "identity": local.state.identity(),
                "maintenance": (local.state.read("maintenance.json") or {}).get("operation"),
            }
            if args.operation:
                identifier(args.operation)
                result["local"] = local.summary(local.state.operation(args.operation))
                result["remote"] = remote.call("inspect", {"operation": args.operation})
            elif not result["maintenance"]:
                try:
                    preview, _, _ = sync.preview()
                    preview.pop("bundle", None)
                    result["drift"] = preview
                except ConfigError as error:
                    result["state"] = error.code
        elif args.action in ("resume", "deploy-finish"):
            identifier(args.operation)
            result = sync.resume(args.operation, args.timeout)
        elif args.action == "recover":
            identifier(args.operation)
            result = sync.recover(
                args.operation, services_stopped=args.services_stopped, timeout=args.timeout
            )
        else:
            if args.action == "init" and args.initial is None:
                raise ConfigError(
                    "missing_source", "Initialization requires --from local or remote"
                )
            kwargs = {
                "mode": args.mode,
                "overwrite": args.overwrite,
                "initial": args.initial if args.action == "init" else None,
            }
            if args.plan:
                result, _, _ = sync.preview(**kwargs)
                result.pop("bundle", None)
            elif args.action == "deploy-prepare":
                operation = sync.prepare(**kwargs, deployment=True)
                local.commit(operation)
                # Shell and PowerShell consume only this validated identifier.
                print(operation)
                return 0
            else:
                result = sync.run(**kwargs, timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ConfigError, ConfigurationBusy, OSError, ValueError) as exc:
        error = (
            exc.as_dict()
            if isinstance(exc, ConfigError)
            else {
                "code": "configuration_busy"
                if isinstance(exc, ConfigurationBusy)
                else "sync_error",
                "message": str(exc)
                if isinstance(exc, ConfigurationBusy)
                else "Configuration sync failed",
            }
        )
        print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
