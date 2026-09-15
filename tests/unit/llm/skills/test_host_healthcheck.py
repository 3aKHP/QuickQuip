"""预置 skill host-healthcheck：SKILL.md 生产加载契约 + collect.py 三层探测。"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from quickquip.llm.skills import MAX_DESCRIPTION_CHARS, scan_skills

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = REPO_ROOT / "skills.example" / "host-healthcheck"
COLLECT_PATH = SKILL_ROOT / "scripts" / "collect.py"

NOW = 1000000000.0
VIEW_LABELS = {"host-proc", "cgroup", "host-metrics-file", "host-mount"}
GROUP_NAMES = {"load", "memory", "uptime", "cpu", "container", "disk", "host_metrics"}

MEMINFO = (
    "MemTotal:       16384000 kB\n"
    "MemFree:         2048000 kB\n"
    "MemAvailable:    8192000 kB\n"
    "Buffers:         1024000 kB\n"
    "Cached:          4096000 kB\n"
    "SwapTotal:       2097152 kB\n"
    "SwapFree:        1048576 kB\n"
)
UPTIME = "98765.43 195000.00\n"
STAT = (
    "cpu  1000 0 500 8000 200 0 100 0 0 0\n"
    "cpu0 500 0 250 4000 100 0 50 0 0 0\n"
    "cpu1 500 0 250 4000 100 0 50 0 0 0\n"
    "btime 1000000000\n"
    "ctxt 12345\n"
)


def _load_collect():
    spec = importlib.util.spec_from_file_location("host_healthcheck_collect", COLLECT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collect = _load_collect()


def _write_proc(root: Path, *, load1: str = "0.42") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "loadavg").write_text(f"{load1} 0.35 0.30 2/480 12345\n", encoding="utf-8")
    (root / "meminfo").write_text(MEMINFO, encoding="utf-8")
    (root / "uptime").write_text(UPTIME, encoding="utf-8")
    (root / "stat").write_text(STAT, encoding="utf-8")
    return root


def _build(tmp_path: Path, **overrides) -> dict:
    kwargs = {
        "proc_root": tmp_path / "proc",
        "cgroup_root": tmp_path / "cgroup",
        "host_proc_root": tmp_path / "host-proc",
        "host_metrics_file": tmp_path / "data" / "host_metrics.json",
        "disk_path": tmp_path / "data",
        "now": NOW,
    }
    kwargs.update(overrides)
    return collect.build_report(**kwargs)


def _env_overrides(tmp_path: Path) -> dict[str, str]:
    return {
        "QQ_HC_PROC_ROOT": str(tmp_path / "proc"),
        "QQ_HC_CGROUP_ROOT": str(tmp_path / "cgroup"),
        "QQ_HC_HOST_PROC_ROOT": str(tmp_path / "host-proc"),
        "QQ_HC_HOST_METRICS_FILE": str(tmp_path / "data" / "host_metrics.json"),
        "QQ_HC_DISK_PATH": str(tmp_path / "data"),
    }


@pytest.fixture
def sandbox(tmp_path):
    _write_proc(tmp_path / "proc")
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.max").write_text(f"{2048 * 1024 * 1024}\n", encoding="utf-8")
    (cgroup / "memory.current").write_text(f"{512 * 1024 * 1024}\n", encoding="utf-8")
    (cgroup / "cpu.max").write_text("200000 100000\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    return tmp_path


# ── L0：/proc 直读与 cgroup 自身限额 ─────────────────────────────


def test_l0_proc_groups_parsed(sandbox):
    groups = _build(sandbox)["groups"]

    load = groups["load"]
    assert load["status"] == "ok" and load["view"] == "host-proc"
    assert load["load1"] == 0.42 and load["load5"] == 0.35 and load["load15"] == 0.30
    assert load["runnable_threads"] == 2 and load["total_threads"] == 480
    assert load["source"].endswith("/proc/loadavg")

    memory = groups["memory"]
    assert memory["status"] == "ok" and memory["view"] == "host-proc"
    assert memory["total_bytes"] == 16384000 * 1024
    assert memory["available_bytes"] == 8192000 * 1024
    assert memory["available_basis"] == "MemAvailable"
    assert memory["used_percent"] == 50.0
    assert memory["swap"] == {"total_bytes": 2097152 * 1024, "free_bytes": 1048576 * 1024}

    uptime = groups["uptime"]
    assert uptime["status"] == "ok" and uptime["view"] == "host-proc"
    assert uptime["seconds"] == 98765.43 and uptime["idle_seconds"] == 195000.00

    cpu = groups["cpu"]
    assert cpu["status"] == "ok" and cpu["view"] == "host-proc"
    assert cpu["cores"] == 2
    assert cpu["boot_time"] == "2001-09-09T01:46:40+00:00"
    assert cpu["since_boot"] == {"busy_percent": 16.3, "idle_percent": 83.7}


def test_l0_cgroup_v2(sandbox):
    group = _build(sandbox)["groups"]["container"]
    assert group["status"] == "ok" and group["view"] == "cgroup"
    assert group["cgroup_version"] == "v2"
    assert group["memory"]["limit_bytes"] == 2048 * 1024 * 1024
    assert group["memory"]["used_bytes"] == 512 * 1024 * 1024
    assert group["memory"]["used_percent"] == 25.0
    assert group["cpu"] == {"quota_cores": 2.0}


def test_l0_cgroup_v2_unlimited(sandbox):
    (sandbox / "cgroup" / "memory.max").write_text("max\n", encoding="utf-8")
    (sandbox / "cgroup" / "cpu.max").write_text("max 100000\n", encoding="utf-8")
    group = _build(sandbox)["groups"]["container"]
    assert group["memory"]["unlimited"] is True
    assert "limit_bytes" not in group["memory"]
    assert group["memory"]["used_bytes"] == 512 * 1024 * 1024
    assert group["cpu"] == {"unlimited": True}


def test_l0_cgroup_v1_fallback(sandbox):
    cgroup = sandbox / "cgroup"
    for child in cgroup.iterdir():
        child.unlink()
    (cgroup / "memory").mkdir()
    (cgroup / "cpu").mkdir()
    (cgroup / "memory" / "memory.limit_in_bytes").write_text(
        f"{256 * 1024 * 1024}\n", encoding="utf-8"
    )
    (cgroup / "memory" / "memory.usage_in_bytes").write_text(
        f"{128 * 1024 * 1024}\n", encoding="utf-8"
    )
    (cgroup / "cpu" / "cpu.cfs_quota_us").write_text("50000\n", encoding="utf-8")
    (cgroup / "cpu" / "cpu.cfs_period_us").write_text("100000\n", encoding="utf-8")
    group = _build(sandbox)["groups"]["container"]
    assert group["status"] == "ok" and group["cgroup_version"] == "v1"
    assert group["memory"]["limit_bytes"] == 256 * 1024 * 1024
    assert group["memory"]["used_percent"] == 50.0
    assert group["cpu"] == {"quota_cores": 0.5}


def test_l0_cgroup_v1_unlimited_threshold(sandbox):
    cgroup = sandbox / "cgroup"
    for child in cgroup.iterdir():
        child.unlink()
    (cgroup / "memory").mkdir()
    (cgroup / "memory" / "memory.limit_in_bytes").write_text(f"{1 << 62}\n", encoding="utf-8")
    group = _build(sandbox)["groups"]["container"]
    assert group["cgroup_version"] == "v1"
    assert group["memory"]["unlimited"] is True
    assert "limit_bytes" not in group["memory"]


def test_l0_cgroup_unavailable_when_empty(tmp_path):
    empty = tmp_path / "cgroup"
    empty.mkdir()
    group = _build(tmp_path, cgroup_root=empty)["groups"]["container"]
    assert group["status"] == "unavailable" and group["view"] == "cgroup"


def test_l0_disk_group_host_mount_view(sandbox):
    disk = _build(sandbox)["groups"]["disk"]
    assert disk["status"] == "ok" and disk["view"] == "host-mount"
    assert disk["total_bytes"] > 0 and disk["used_bytes"] > 0
    assert disk["source"] == str(sandbox / "data")


# ── L1：宿主机 cron 采集文件 ─────────────────────────────────────


def _write_metrics(path: Path, age_seconds: float) -> dict:
    payload = {"processes": 120, "disks": [{"mount": "/", "total_bytes": 51200000}]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    moment = NOW - age_seconds
    os.utime(path, (moment, moment))
    return payload


def test_l1_metrics_fresh(sandbox):
    payload = _write_metrics(sandbox / "data" / "host_metrics.json", age_seconds=30)
    report = _build(sandbox)
    group = report["groups"]["host_metrics"]
    assert report["levels"]["L1"] is True
    assert group["status"] == "ok" and group["view"] == "host-metrics-file"
    assert group["metrics"] == payload
    assert group["age_seconds"] == 30
    assert group["file_mtime"] == "2001-09-09T01:46:10+00:00"


def test_l1_metrics_stale_still_merged(sandbox):
    payload = _write_metrics(sandbox / "data" / "host_metrics.json", age_seconds=1000)
    report = _build(sandbox)
    group = report["groups"]["host_metrics"]
    assert group["status"] == "stale" and group["view"] == "host-metrics-file"
    assert group["age_seconds"] == 1000
    assert group["metrics"] == payload


def test_l1_metrics_missing(sandbox):
    report = _build(sandbox)
    group = report["groups"]["host_metrics"]
    assert report["levels"]["L1"] is False
    assert group["status"] == "unavailable" and group["view"] == "host-metrics-file"


def test_l1_metrics_corrupt(sandbox):
    target = sandbox / "data" / "host_metrics.json"
    target.write_text("not-json{", encoding="utf-8")
    report = _build(sandbox)
    group = report["groups"]["host_metrics"]
    assert report["levels"]["L1"] is True
    assert group["status"] == "unavailable"
    assert "metrics" not in group


# ── L2：/host/proc 只读挂载优先 ──────────────────────────────────


def test_l2_host_proc_mount_preferred(sandbox):
    host_proc = _write_proc(sandbox / "host-proc", load1="9.99")
    report = _build(sandbox)
    assert report["levels"]["L2"] is True
    load = report["groups"]["load"]
    assert load["view"] == "host-proc"
    assert load["source"].startswith(str(host_proc))
    assert load["load1"] == 9.99


def test_l2_absent_falls_back_to_proc(sandbox):
    report = _build(sandbox)
    assert report["levels"]["L2"] is False
    assert report["groups"]["load"]["source"].startswith(str(sandbox / "proc"))


# ── 视图标注、输出契约与优雅降级 ──────────────────────────────────


def test_view_labels_enum_and_views_doc(sandbox):
    report = _build(sandbox)
    assert set(report["views"]) == VIEW_LABELS
    assert all(isinstance(text, str) and text for text in report["views"].values())
    for group in report["groups"].values():
        assert group["view"] in VIEW_LABELS
        assert group["status"] in {"ok", "stale", "unavailable"}


def test_report_contract(sandbox):
    report = _build(sandbox)
    for key in (
        "schema",
        "generated_at",
        "platform",
        "levels",
        "views",
        "groups",
        "reporting_rule",
    ):
        assert key in report
    assert report["schema"] == collect.SCHEMA
    assert report["levels"]["L0"] is True
    assert set(report["groups"]) == GROUP_NAMES
    json.dumps(report, ensure_ascii=False)


def test_non_linux_degradation(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    report = _build(
        tmp_path,
        proc_root=empty,
        cgroup_root=empty,
        host_proc_root=empty,
        host_metrics_file=tmp_path / "data" / "host_metrics.json",
        disk_path=tmp_path,
    )
    for name in ("load", "memory", "uptime", "cpu", "container", "host_metrics"):
        assert report["groups"][name]["status"] == "unavailable", name
    assert report["groups"]["disk"]["status"] == "ok"
    assert report["levels"] == {"L0": True, "L1": False, "L2": False}


def test_main_entrypoint_via_env_overrides(sandbox, monkeypatch, capsys):
    for key, value in _env_overrides(sandbox).items():
        monkeypatch.setenv(key, value)
    assert collect.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema"] == collect.SCHEMA
    assert report["groups"]["load"]["status"] == "ok"


def test_script_subprocess_whitelisted_env(sandbox):
    env = {"PATH": os.environ.get("PATH", ""), **_env_overrides(sandbox)}
    result = subprocess.run(
        [sys.executable, str(COLLECT_PATH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema"] == collect.SCHEMA


# ── SKILL.md 生产加载契约 ────────────────────────────────────────


def test_skill_loads_via_production_scan():
    skills = {skill.name: skill for skill in scan_skills(REPO_ROOT / "skills.example")}
    skill = skills["host-healthcheck"]
    assert len(skill.metadata.description) <= MAX_DESCRIPTION_CHARS
    assert "当用户" in skill.metadata.description
    assert "宿主机" in skill.metadata.description
    script = next(r for r in skill.resources if r.path == "scripts/collect.py")
    assert script.kind == "script" and script.sha256
    assert all(not r.path.startswith("references/") for r in skill.resources)


def test_collect_script_stdlib_only():
    tree = ast.parse(COLLECT_PATH.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    assert modules <= sys.stdlib_module_names
