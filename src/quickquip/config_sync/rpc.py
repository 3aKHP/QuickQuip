"""Container-side JSON protocol. Called through authenticated SSH, never exposed over HTTP."""

import argparse
import json
import os
from pathlib import Path
import sys

from quickquip.common.config_writes import (
    ConfigurationBusy,
    check_writable,
)
from quickquip.common.env import PROJECT_ROOT, load_root_env_file
from quickquip.config_sync.bundle import (
    MAX_BYTES,
    digest,
    validate_bundle,
    read_assets,
    install_assets,
)
from quickquip.config_sync.endpoint import Endpoint
from quickquip.llm.config_errors import ConfigError


def execute(endpoint, action, body):
    if action == "read":
        result = endpoint.capture(body.get("source", "published"))
        peer = body.get("peer")
        result["base"] = endpoint.state.baseline(peer) if peer else None
        return result
    if action == "identity":
        return endpoint.initialize_identity()
    if action == "preflight":
        from quickquip.llm.config_document import environment_references

        candidate = validate_bundle(body["bundle"])
        return {
            "environment": [
                {"name": name, "configured": bool(os.getenv(name))}
                for name in sorted(set(environment_references(candidate["document"])))
            ]
        }
    operation = body["operation"]
    if action == "cancel-preparation":
        return endpoint.cancel_preparation(operation, body["expected_endpoint"])
    if action == "inspect":
        record = endpoint.state.operation(operation)
        return {
            **endpoint.summary(record),
            "deployment": record.get("deployment"),
            "deployment_pending": record.get("deployment_pending", False),
        }
    if action == "release-terminal":
        return endpoint.release_terminal(operation)
    if action == "prepare":
        return endpoint.prepare(
            operation,
            body["bundle"],
            body["expected"],
            publish=True,
            overwrite=body.get("overwrite", False),
            deployment=body.get("deployment", False),
        )
    if action == "commit":
        return endpoint.commit(operation)
    if action == "wait":
        return endpoint.wait(operation, body.get("timeout", 150))
    if action == "restart-fence":
        return endpoint.fence_stopped_bot(operation)
    if action == "recover":
        return endpoint.recover(
            operation, services_stopped=body.get("services_stopped", False), defer_release=True
        )
    if action == "recovery-verified":
        return endpoint.verify_recovery(operation)
    if action == "confirm":
        return endpoint.confirm(operation, body["peer"])
    if action == "bind-deployment":
        with endpoint.owned_operation(operation) as record:
            if record["phase"] != "prepared" or not record["deployment_pending"]:
                raise ConfigError("operation_conflict", "Operation is not prepared for deployment")
            if record.get("deployment") not in (None, body["release"]):
                raise ConfigError("operation_conflict", "Operation belongs to another deployment")
            record["deployment"] = body["release"]
            endpoint.state.save_operation(record)
            return endpoint.summary(record)
    if action == "verify-committed":
        from quickquip.llm.config_wait import wait_loaded

        with endpoint.owned_operation(operation) as record:
            if record["phase"] not in ("committed", "confirmed"):
                raise ConfigError(
                    "operation_conflict", "Deployment has not committed configuration"
                )
            if digest(endpoint.capture("published")["bundle"]) != digest(record["target"]):
                raise ConfigError("revision_conflict", "Committed configuration changed")
            wait_loaded(
                endpoint.service,
                record["revision"],
                timeout=0,
                previous_boot=record.get("boot_before_restart"),
            )
            return endpoint.summary(record)
    if action == "stage":
        with endpoint.owned_operation(operation) as record:
            if record["phase"] != "prepared":
                raise ConfigError(
                    "operation_conflict", "Deployment stage requires a prepared operation"
                )
            # The caller mounts a new candidate directory; the live release remains untouched.
            validate_bundle(record["target"], environment=True)
            validate_bundle(
                {**record["target"], "document": record["before"]["published"]}, environment=True
            )
            record["deployment"] = body["release"]
            record["phase"] = "staging"
            endpoint.state.save_operation(record)
            endpoint._assets(record["target"]["assets"])
            validate_bundle({**record["target"], "document": record["before"]["published"]})
            record["phase"] = "staged"
            endpoint.state.save_operation(record)
            return endpoint.summary(record)
    if action == "candidate-commit":
        with endpoint.owned_operation(operation) as record:
            if not record.get("deployment"):
                raise ConfigError("operation_conflict", "No staged deployment")
            current = endpoint.version()
            expected = dict(record["expected"], assets_hash=digest(record["target"]["assets"]))
            if current != expected:
                raise ConfigError("revision_conflict", "Candidate changed before activation")
            record["expected"] = expected
            record["phase"] = "prepared"
            endpoint.state.save_operation(record)
            return endpoint.commit(operation)
    raise ConfigError("invalid_command", "Unknown synchronization operation")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--operation")
    parser.add_argument("--release")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--timeout", type=int, default=150)
    args = parser.parse_args(argv)
    load_root_env_file()
    try:
        if args.action == "idle":
            check_writable(args.root / "data")
            print('{"idle": true}')
            return 0
        if args.action == "preserve":
            check_writable(args.root / "data")
            install_assets(args.root, read_assets(Path("/sync-previous")))
            print('{"preserved": true}')
            return 0
        if args.operation:
            body = {
                "operation": args.operation,
                "services_stopped": args.services_stopped,
                "release": args.release,
                "timeout": args.timeout,
            }
        else:
            raw = sys.stdin.buffer.read(MAX_BYTES * 2 + 1)
            if len(raw) > MAX_BYTES * 2:
                raise ConfigError("body_too_large", "Synchronization request exceeds its limit")
            body = json.loads(raw)
        result = execute(Endpoint(args.root), args.action, body)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ConfigError, ConfigurationBusy, OSError, ValueError, KeyError) as exc:
        error = (
            exc.as_dict()
            if isinstance(exc, ConfigError)
            else {
                "code": "configuration_busy"
                if isinstance(exc, ConfigurationBusy)
                else "sync_error",
                "message": str(exc)
                if isinstance(exc, ConfigurationBusy)
                else "Synchronization request failed",
            }
        )
        print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
