#!/usr/bin/env python3
"""QuickQuip host metrics collector, intended for cron on the Docker host.

L1 enhancement of the host-healthcheck skill: writes
<root>/data/host_metrics.json atomically once per run (process count, full
disk view, temperatures when sensors exist). The quickquip container reads it
read-only through the existing data/ bind mount; nothing is exposed back.

Install (crontab -e on the host):

    * * * * * /usr/bin/python3 /opt/QuickQuip/prod/host_metrics_collector.py

QUICKQUIP_ROOT defaults to /opt/QuickQuip (the deployment root whose data/ is
bind-mounted into the container); set it as a crontab environment line when the
deployment root differs. Append a shell redirect to keep a log if wanted.
Pure Python 3 standard library.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "quickquip.host-metrics/1"
DEPLOY_ROOT = Path(os.environ.get("QUICKQUIP_ROOT", "/opt/QuickQuip"))
OUTPUT = DEPLOY_ROOT / "data" / "host_metrics.json"

PSEUDO_FS_TYPES = {
    "autofs",
    "bpf",
    "cgroup",
    "cgroup2",
    "configfs",
    "debugfs",
    "devpts",
    "devtmpfs",
    "efivarfs",
    "fusectl",
    "hugetlbfs",
    "mqueue",
    "nsfs",
    "overlay",
    "proc",
    "pstore",
    "ramfs",
    "securityfs",
    "squashfs",
    "sysfs",
    "tmpfs",
    "tracefs",
}


def collect_processes() -> int | None:
    try:
        return sum(1 for entry in os.listdir("/proc") if entry.isdigit())
    except OSError:
        return None


def collect_disks() -> list[dict]:
    try:
        lines = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    disks = []
    seen_devices = set()
    for line in lines:
        fields = line.split()
        if len(fields) < 3 or fields[2] in PSEUDO_FS_TYPES:
            continue
        device, mount_point = fields[0], fields[1].replace("\\040", " ")
        if not device.startswith("/"):
            continue
        try:
            st_dev = os.stat(mount_point).st_dev
            usage = os.statvfs(mount_point)
        except OSError:
            continue
        if st_dev in seen_devices:
            continue
        seen_devices.add(st_dev)
        block_size = usage.f_frsize or usage.f_bsize
        total = usage.f_blocks * block_size
        used = total - usage.f_bfree * block_size
        available = usage.f_bavail * block_size
        disks.append(
            {
                "mount": mount_point,
                "filesystem": device,
                "total_bytes": total,
                "used_bytes": used,
                "available_bytes": available,
                "used_percent": round(used / total * 100, 1) if total else None,
            }
        )
    return disks


def collect_temperatures() -> list[dict]:
    temperatures = []
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        try:
            raw = (zone / "temp").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        try:
            label = (zone / "type").read_text(encoding="utf-8").strip()
        except OSError:
            label = zone.name
        try:
            millidegree = int(raw)
        except ValueError:
            continue
        temperatures.append({"zone": label, "celsius": round(millidegree / 1000, 1)})
    return temperatures


def main() -> int:
    now = time.time()
    payload = {
        "schema": SCHEMA,
        "collected_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(
            timespec="seconds"
        ),
        "collected_at_epoch": round(now, 3),
    }
    processes = collect_processes()
    if processes is not None:
        payload["processes"] = processes
    disks = collect_disks()
    if disks:
        payload["disks"] = disks
    temperatures = collect_temperatures()
    if temperatures:
        payload["temperatures"] = temperatures
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".host_metrics.", dir=OUTPUT.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, OUTPUT)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
