"""host-healthcheck 采集脚本：三层宿主感知探测，输出机器可读 JSON。

L0（零配置默认）：/proc 直读负载/内存/开机时长/CPU（Linux 容器内这些文件
即宿主机整机值）、cgroup 自身限额用量、data 卷磁盘用量。
L1：宿主机 cron 采集器写入的 data/host_metrics.json，存在即并入并标注新鲜度。
L2：部署者只读挂载 /host/proc 时，优先作为 host-proc 视图来源。

文件缺失或非 Linux 平台时对应指标组标 unavailable，其余组不受影响，退出码
恒为 0。仅使用 Python 标准库。探测根可用环境变量覆盖（默认生产值）：

QQ_HC_PROC_ROOT / QQ_HC_CGROUP_ROOT / QQ_HC_HOST_PROC_ROOT /
QQ_HC_HOST_METRICS_FILE / QQ_HC_DISK_PATH / QQ_HC_HOST_METRICS_MAX_AGE
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "quickquip.host-healthcheck/1"

VIEW_HOST_PROC = "host-proc"
VIEW_CGROUP = "cgroup"
VIEW_HOST_METRICS_FILE = "host-metrics-file"
VIEW_HOST_MOUNT = "host-mount"

VIEWS = {
    VIEW_HOST_PROC: (
        "proc 虚拟文件系统直读的整机指标。Linux 容器对 loadavg/meminfo/uptime/stat "
        "不做命名空间隔离，容器内读到即宿主机值；source 以 /host/proc 开头时取自"
        "部署者显式只读挂载的宿主机 proc。"
    ),
    VIEW_CGROUP: "容器自身的资源限额与用量，仅约束本容器进程，不反映宿主机整机水位。",
    VIEW_HOST_METRICS_FILE: (
        "宿主机 cron 采集器写入 data/host_metrics.json 的实测数据；status 为 stale "
        "或 age_seconds 偏大说明采集器可能已停止。"
    ),
    VIEW_HOST_MOUNT: (
        "经 bind mount 观测到的宿主机存储：data/ 卷位于宿主机真实磁盘分区，"
        "用量为该分区的 df 语义值。"
    ),
}

REPORTING_RULE = (
    "转述时按 view 区分来源：host-proc / host-mount / host-metrics-file 为宿主机实测，"
    "cgroup 为容器自身限额视角；stale 与 unavailable 必须如实说明，不得推测补全。"
)

DEFAULT_PROC_ROOT = "/proc"
DEFAULT_CGROUP_ROOT = "/sys/fs/cgroup"
DEFAULT_HOST_PROC_ROOT = "/host/proc"
DEFAULT_STALE_AFTER_SECONDS = 300
MAX_HOST_METRICS_BYTES = 256 * 1024
_V1_UNLIMITED_THRESHOLD = 1 << 60


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _unavailable(view: str, source: Path, reason: str) -> dict:
    return {"status": "unavailable", "view": view, "source": str(source), "reason": reason}


def _collect_load(proc_root: Path) -> dict:
    source = proc_root / "loadavg"
    text = _read_text(source)
    if text is None:
        return _unavailable(VIEW_HOST_PROC, source, "loadavg 不可读")
    parts = text.split()
    try:
        running, _, total = parts[3].partition("/")
        return {
            "status": "ok",
            "view": VIEW_HOST_PROC,
            "source": str(source),
            "load1": float(parts[0]),
            "load5": float(parts[1]),
            "load15": float(parts[2]),
            "runnable_threads": int(running),
            "total_threads": int(total),
            "cpu_count": os.cpu_count(),
        }
    except (IndexError, ValueError):
        return _unavailable(VIEW_HOST_PROC, source, "loadavg 格式异常")


def _collect_memory(proc_root: Path) -> dict:
    source = proc_root / "meminfo"
    text = _read_text(source)
    if text is None:
        return _unavailable(VIEW_HOST_PROC, source, "meminfo 不可读")
    fields: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            fields[key.strip()] = int(parts[0]) * 1024
    total = fields.get("MemTotal")
    available = fields.get("MemAvailable")
    basis = "MemAvailable"
    if available is None:
        available = fields.get("MemFree")
        basis = "MemFree"
    if not total or available is None:
        return _unavailable(VIEW_HOST_PROC, source, "meminfo 缺少 MemTotal/MemAvailable")
    group = {
        "status": "ok",
        "view": VIEW_HOST_PROC,
        "source": str(source),
        "total_bytes": total,
        "available_bytes": available,
        "available_basis": basis,
        "used_percent": round((1 - available / total) * 100, 1),
    }
    swap_total = fields.get("SwapTotal")
    swap_free = fields.get("SwapFree")
    if swap_total is not None and swap_free is not None:
        group["swap"] = {"total_bytes": swap_total, "free_bytes": swap_free}
    return group


def _collect_uptime(proc_root: Path) -> dict:
    source = proc_root / "uptime"
    text = _read_text(source)
    if text is None:
        return _unavailable(VIEW_HOST_PROC, source, "uptime 不可读")
    parts = text.split()
    try:
        return {
            "status": "ok",
            "view": VIEW_HOST_PROC,
            "source": str(source),
            "seconds": float(parts[0]),
            "idle_seconds": float(parts[1]),
        }
    except (IndexError, ValueError):
        return _unavailable(VIEW_HOST_PROC, source, "uptime 格式异常")


def _collect_cpu(proc_root: Path) -> dict:
    source = proc_root / "stat"
    text = _read_text(source)
    if text is None:
        return _unavailable(VIEW_HOST_PROC, source, "stat 不可读")
    aggregate = ""
    cores = 0
    btime: int | None = None
    for line in text.splitlines():
        if line.startswith("cpu "):
            aggregate = line
        elif line.startswith("cpu") and line[3:4].isdigit():
            cores += 1
        elif line.startswith("btime"):
            fields = line.split()
            if len(fields) == 2 and fields[1].isdigit():
                btime = int(fields[1])
    if not aggregate:
        return _unavailable(VIEW_HOST_PROC, source, "stat 缺少 cpu 聚合行")
    try:
        values = [int(value) for value in aggregate.split()[1:]]
    except ValueError:
        return _unavailable(VIEW_HOST_PROC, source, "stat cpu 行格式异常")
    values += [0] * (8 - len(values))
    user, nice, system, idle, iowait, irq, softirq, steal = values[:8]
    busy = user + nice + system + irq + softirq + steal
    idle_all = idle + iowait
    total = busy + idle_all
    if total <= 0:
        return _unavailable(VIEW_HOST_PROC, source, "stat cpu 行计数为零")
    group = {
        "status": "ok",
        "view": VIEW_HOST_PROC,
        "source": str(source),
        "cores": cores,
        "since_boot": {
            "busy_percent": round(busy / total * 100, 1),
            "idle_percent": round(idle_all / total * 100, 1),
        },
    }
    if btime is not None:
        group["boot_time"] = _iso(btime)
    return group


def _quota_cores(quota_text: str, period_text: str) -> float | None:
    try:
        quota = int(quota_text)
        period = int(period_text)
    except ValueError:
        return None
    if quota <= 0 or period <= 0:
        return None
    return round(quota / period, 2)


def _memory_group(limit_bytes: int | None, used_bytes: int | None) -> dict:
    memory: dict = {}
    if limit_bytes is None:
        memory["unlimited"] = True
    else:
        memory["limit_bytes"] = limit_bytes
    if used_bytes is not None:
        memory["used_bytes"] = used_bytes
    if limit_bytes and used_bytes is not None:
        memory["used_percent"] = round(used_bytes / limit_bytes * 100, 1)
    return memory


def _collect_cgroup(cgroup_root: Path) -> dict:
    if (cgroup_root / "memory.max").is_file():
        limit_text = (_read_text(cgroup_root / "memory.max") or "").strip()
        limit_bytes = int(limit_text) if limit_text.isdigit() else None
        current_text = (_read_text(cgroup_root / "memory.current") or "").strip()
        used_bytes = int(current_text) if current_text.isdigit() else None
        cpu_fields = (_read_text(cgroup_root / "cpu.max") or "").split()
        cpu: dict = {"unlimited": True}
        if len(cpu_fields) >= 2 and cpu_fields[0] != "max":
            cores = _quota_cores(cpu_fields[0], cpu_fields[1])
            cpu = {"quota_cores": cores} if cores is not None else {}
        return {
            "status": "ok",
            "view": VIEW_CGROUP,
            "source": str(cgroup_root),
            "cgroup_version": "v2",
            "memory": _memory_group(limit_bytes, used_bytes),
            "cpu": cpu,
        }
    v1_limit = cgroup_root / "memory" / "memory.limit_in_bytes"
    if v1_limit.is_file():
        limit_text = (_read_text(v1_limit) or "").strip()
        limit_bytes = int(limit_text) if limit_text.isdigit() else None
        if limit_bytes is not None and limit_bytes >= _V1_UNLIMITED_THRESHOLD:
            limit_bytes = None
        usage_text = (_read_text(cgroup_root / "memory" / "memory.usage_in_bytes") or "").strip()
        used_bytes = int(usage_text) if usage_text.isdigit() else None
        quota_text = (_read_text(cgroup_root / "cpu" / "cpu.cfs_quota_us") or "").strip()
        period_text = (_read_text(cgroup_root / "cpu" / "cpu.cfs_period_us") or "").strip()
        cores = _quota_cores(quota_text, period_text)
        cpu = {"quota_cores": cores} if cores is not None else {"unlimited": True}
        return {
            "status": "ok",
            "view": VIEW_CGROUP,
            "source": str(cgroup_root),
            "cgroup_version": "v1",
            "memory": _memory_group(limit_bytes, used_bytes),
            "cpu": cpu,
        }
    return _unavailable(VIEW_CGROUP, cgroup_root, "未找到 cgroup v2/v1 限额文件")


def _collect_disk(disk_path: Path) -> dict:
    try:
        usage = shutil.disk_usage(disk_path)
    except OSError:
        return _unavailable(VIEW_HOST_MOUNT, disk_path, "目标路径不可探测")
    return {
        "status": "ok",
        "view": VIEW_HOST_MOUNT,
        "source": str(disk_path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_percent": round(usage.used / usage.total * 100, 1) if usage.total else None,
    }


def _collect_host_metrics(path: Path, *, now: float, stale_after: int) -> tuple[dict, bool]:
    if not path.is_file():
        return (
            _unavailable(VIEW_HOST_METRICS_FILE, path, "采集文件不存在，宿主机 cron 采集器未部署"),
            False,
        )
    try:
        info = path.stat()
    except OSError:
        return _unavailable(VIEW_HOST_METRICS_FILE, path, "无法读取采集文件状态"), True
    if info.st_size > MAX_HOST_METRICS_BYTES:
        return _unavailable(VIEW_HOST_METRICS_FILE, path, "采集文件超过大小上限"), True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _unavailable(VIEW_HOST_METRICS_FILE, path, "采集文件不是有效 JSON"), True
    if not isinstance(payload, dict):
        return _unavailable(VIEW_HOST_METRICS_FILE, path, "采集文件顶层不是对象"), True
    age = max(0.0, now - info.st_mtime)
    status = "ok" if age <= stale_after else "stale"
    return (
        {
            "status": status,
            "view": VIEW_HOST_METRICS_FILE,
            "source": str(path),
            "file_mtime": _iso(info.st_mtime),
            "age_seconds": round(age, 1),
            "stale_after_seconds": stale_after,
            "metrics": payload,
        },
        True,
    )


def _select_proc_root(proc_root: Path, host_proc_root: Path) -> tuple[Path, bool]:
    if (host_proc_root / "loadavg").is_file():
        return host_proc_root, True
    return proc_root, False


def build_report(
    *,
    proc_root: Path,
    cgroup_root: Path,
    host_proc_root: Path,
    host_metrics_file: Path,
    disk_path: Path,
    now: float | None = None,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> dict:
    moment = time.time() if now is None else now
    effective_proc, host_proc_mounted = _select_proc_root(proc_root, host_proc_root)
    host_metrics, metrics_deployed = _collect_host_metrics(
        host_metrics_file, now=moment, stale_after=stale_after_seconds
    )
    return {
        "schema": SCHEMA,
        "generated_at": _iso(moment),
        "platform": sys.platform,
        "levels": {
            "L0": True,
            "L1": metrics_deployed,
            "L2": host_proc_mounted,
        },
        "views": VIEWS,
        "groups": {
            "load": _collect_load(effective_proc),
            "memory": _collect_memory(effective_proc),
            "uptime": _collect_uptime(effective_proc),
            "cpu": _collect_cpu(effective_proc),
            "container": _collect_cgroup(cgroup_root),
            "disk": _collect_disk(disk_path),
            "host_metrics": host_metrics,
        },
        "reporting_rule": REPORTING_RULE,
    }


def _default_data_dir() -> Path:
    cwd = Path.cwd()
    for parent in (cwd, *cwd.parents):
        candidate = parent / "data"
        if candidate.is_dir():
            return candidate
    return cwd


def resolve_config(env: Mapping[str, str]) -> dict:
    data_dir = _default_data_dir()
    return {
        "proc_root": Path(env.get("QQ_HC_PROC_ROOT", DEFAULT_PROC_ROOT)),
        "cgroup_root": Path(env.get("QQ_HC_CGROUP_ROOT", DEFAULT_CGROUP_ROOT)),
        "host_proc_root": Path(env.get("QQ_HC_HOST_PROC_ROOT", DEFAULT_HOST_PROC_ROOT)),
        "host_metrics_file": Path(
            env.get("QQ_HC_HOST_METRICS_FILE", str(data_dir / "host_metrics.json"))
        ),
        "disk_path": Path(env.get("QQ_HC_DISK_PATH", str(data_dir))),
        "stale_after_seconds": int(
            env.get("QQ_HC_HOST_METRICS_MAX_AGE", DEFAULT_STALE_AFTER_SECONDS)
        ),
    }


def main() -> int:
    report = build_report(**resolve_config(os.environ))
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
