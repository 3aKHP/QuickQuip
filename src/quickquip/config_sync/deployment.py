"""Machine hooks joining directional configuration sync to a code deployment."""

import argparse
import json
from pathlib import Path
import sys
import time
import uuid

from filelock import FileLock

from quickquip.common.env import PROJECT_ROOT
from quickquip.config_sync.session import Session, public_preview
from quickquip.configuration.deployment import Deployment
from quickquip.configuration.errors import ConfigError


def prepare(session, direction):
    mode = session.mode(required=True)
    if (mode.location, mode.runtime) != ("cloud", "docker"):
        raise ConfigError(
            "deployment_mode_mismatch", "deploy-v4 requires cloud/docker in root .env"
        )
    session.state.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with FileLock(str(session.state.directory / "qqsync-client.lock"), timeout=1):
        pending = session.pending()
        if pending:
            session._continue(pending)
        plan = session.preview(direction, required=True)
        if plan["conflicts"]:
            raise ConfigError(
                "configuration_conflict",
                "Resolve conflicts with qqsync before deploying",
                details={"conflicts": plan["conflicts"]},
            )
        local, remote = session._peers(mode)
        before = plan["_inputs"]["remote_before"]
        target = plan["target"] if direction == "push" else before["snapshot"]
        record = {
            **plan["_inputs"],
            "id": uuid.uuid4().hex,
            "phase": "preparing",
            "deployment": True,
            "direction": direction,
            "prefer": None,
            "remote_before": before,
            "remote_target": target,
            "remote_original": remote.controller.inspect(),
        }
        if direction == "pull":
            record["original"] = local.controller.inspect()
        session.state.write("qqsync/client.json", record)
        remote.call(
            "prepare",
            {"operation": record["id"], "expected": before, "target": target, "publish": True},
        )
        if direction == "pull":
            local.call(
                "prepare",
                {
                    "operation": record["id"],
                    "expected": record["before"],
                    "target": record["target"],
                    "publish": False,
                },
            )
            local.controller.pause(record["original"])
            local.call("install", {"operation": record["id"]})
            local.controller.restore(record["original"])
            local.controller.verify(record["original"])
        session._save(record, "prepared")
        return record["id"]


def _restore_local(session, local, record):
    if record["direction"] == "pull":
        operation = {"operation": record["id"]}
        try:
            local.call("inspect", operation)
        except ConfigError as error:
            if error.code == "operation_missing":
                session._save(record, "recovered")
                return
            raise
        local.controller.pause(record["original"])
        local.call("restore", operation)
        local.controller.restore(record["original"])
        local.controller.verify(record["original"])
        local.call("recovered", operation)
    session._save(record, "recovered")


def finish(session, record=None, *, timeout=240):
    record = record or session.pending()
    if record is None:
        return {"phase": "confirmed"}
    if not record.get("deployment"):
        return session._continue(record)
    mode = Deployment(**record["route"])
    local, remote = session._peers(mode)
    if remote.runtime == "docker":
        remote.controller.bind(record["remote_original"])
    operation = {"operation": record["id"]}
    deadline = time.monotonic() + timeout
    while True:
        try:
            status = remote.call("inspect", operation)
        except ConfigError as error:
            if error.code != "operation_missing":
                raise
            # Preparation may not have reached the server before the client disconnected.
            remote.call(
                "prepare",
                {
                    **operation,
                    "expected": record["remote_before"],
                    "target": record["remote_target"],
                    "publish": True,
                },
            )
            status = remote.call("inspect", operation)
        release = status.get("deployment")
        if not release:
            remote.call("restore", operation)
            remote.call("recovered", operation)
            _restore_local(session, local, record)
            return {"phase": "recovered", "message": "Unstarted deployment preparation recovered"}
        code = remote.deployment_status(release)
        if code == "0":
            break
        if code != "pending":
            if code == "superseded":
                raise ConfigError("deployment_changed", "Another release replaced this deployment")
            if status["phase"] != "recovered":
                remote.recover_deployment(record["id"], release)
                if remote.call("inspect", operation)["phase"] != "recovered":
                    raise ConfigError(
                        "recovery_pending", "Remote deployment recovery is incomplete"
                    )
            _restore_local(session, local, record)
            raise ConfigError("deployment_failed", "Code deployment failed; configuration restored")
        if time.monotonic() >= deadline:
            raise ConfigError(
                "deployment_pending", "Deployment is running; repeat qqsync to continue"
            )
        time.sleep(1)
    remote.call("verify", {**operation, "running": True})
    if record["direction"] == "pull":
        local.call("verify", operation)
        local.call("confirm", operation)
    remote.call("confirm", operation)
    session._acknowledge(record)
    session._save(record, "confirmed")
    return {"phase": "confirmed", "direction": record["direction"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("connection", "deploy-prepare", "deploy-finish", "plan"))
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--mode", choices=("push", "pull"), default="push")
    parser.add_argument("--host-alias")
    parser.add_argument("--remote-dir")
    parser.add_argument("--operation")
    args = parser.parse_args(argv)
    session = Session(args.root, host=args.host_alias, remote_dir=args.remote_dir)
    try:
        if args.action == "connection":
            mode = session.mode()
            print(mode.host, mode.remote_dir)
            return 0
        if args.action == "deploy-prepare":
            print(prepare(session, args.mode))
            return 0
        if args.action == "plan":
            result = public_preview(session.preview(args.mode))
        else:
            pending = session.pending()
            if pending and args.operation not in (None, pending["id"]):
                raise ConfigError(
                    "operation_conflict", "Another configuration deployment is pending"
                )
            result = finish(session)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ConfigError, OSError, ValueError) as exc:
        error = (
            exc.as_dict()
            if isinstance(exc, ConfigError)
            else {
                "code": "deployment_configuration_failed",
                "message": "Repeat the deployment command",
            }
        )
        print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
