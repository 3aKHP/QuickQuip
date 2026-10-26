"""Real native subprocesses retain their supervisor and exit cleanly during deployment."""

import os
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from quickquip.configuration.activity import stopped_service, Lease
from quickquip.configuration.process_control import request, status


def wait_for(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("Controlled process did not reach the expected state")


@pytest.fixture
def native_services(tmp_path):
    worker = tmp_path / "worker.py"
    worker.write_text('''from pathlib import Path
import os
import sys
import time
from quickquip.configuration.activity import service_guard
from quickquip.configuration.process_supervisor import managed_entrypoint
role, root = sys.argv[1], Path(sys.argv[2])
def record(event):
    with (root / (role + ".events")).open("a") as stream:
        stream.write(f"{event}:{os.getpid()}\\n")
def run():
    with service_guard(root, role):
        record("started")
        try:
            while True:
                time.sleep(0.02)
        except KeyboardInterrupt:
            pass
        finally:
            record("stopped")
record("invoked")
raise SystemExit(managed_entrypoint(root, role, run))
''', encoding="utf-8")
    processes, logs = [], []

    def start(role, *, windowless=False):
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3] / "src")}
        for name in ("QUICKQUIP_MANAGED_CONTAINER", "_QUICKQUIP_SERVICE_CHILD",
                     "_QUICKQUIP_SERVICE_CHILD_ID", "_QUICKQUIP_SERVICE_SUPERVISOR_ID"):
            env.pop(name, None)
        log = (tmp_path / f"{role}-{len(processes)}.log").open("wb")
        executable = (
            str(Path(sys.executable).with_name("pythonw.exe")) if windowless else sys.executable
        )
        process = subprocess.Popen(
            [executable, str(worker), role, str(tmp_path)], cwd=tmp_path,
            env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        processes.append((role, process))
        logs.append(log)
        def started():
            state = status(tmp_path, role)
            events = tmp_path / f"{role}.events"
            return (
                state["record"] is not None and state["record"]["state"] == "running"
                and events.exists()
                and f"started:{state['record']['child_pid']}" in events.read_text()
            )
        try:
            wait_for(started)
        except AssertionError:
            pytest.fail(
                f"Service startup failed (exit={process.poll()}): "
                + (tmp_path / f"{role}-{len(processes) - 1}.log").read_text(
                    encoding="utf-8", errors="replace"
                )
            )
        return process

    yield tmp_path, start
    for role, process in reversed(processes):
        if process.poll() is None:
            try:
                request(tmp_path, role, "stop", timeout=5)
                process.wait(timeout=5)
            except Exception:
                process.kill()
                process.wait(timeout=5)
        wait_for(lambda: not status(tmp_path, role)["running"])
    for log in logs:
        log.close()


@pytest.mark.parametrize("role", ["bot", "web"])
def test_pause_and_resume_retains_supervisor_and_runs_shutdown_cleanup(native_services, role):
    root, start = native_services
    process = start(role)
    first = status(root, role)["record"]["child_pid"]
    request(root, role, "pause")
    assert process.poll() is None
    assert not status(root, role)["running"]
    assert f"stopped:{first}" in (root / f"{role}.events").read_text()
    with stopped_service(root, role) as stopped:
        stopped.verify(root, role)
    request(root, role, "resume")
    wait_for(lambda: status(root, role)["record"]["state"] == "running")
    assert status(root, role)["record"]["child_pid"] != first
    assert status(root, role)["record"]["pid"] == process.pid
    request(root, role, "stop")
    assert process.wait(timeout=5) == 0
    assert (root / f"{role}.events").read_text().count("stopped:") == 2
    # A prior supervisor's stop request must not stop a new invocation.
    replacement = start(role)
    assert replacement.poll() is None
    assert status(root, role)["record"]["pid"] == replacement.pid


def test_control_of_bot_keeps_web_running(native_services):
    root, start = native_services
    start("bot")
    start("web")
    web = status(root, "web")["record"]["child_pid"]
    request(root, "bot", "pause")
    assert not status(root, "bot")["running"]
    assert status(root, "web")["running"]
    assert status(root, "web")["record"]["child_pid"] == web


def test_child_exits_cleanly_when_its_supervisor_disappears(native_services):
    root, start = native_services
    process = start("bot")
    child = status(root, "bot")["record"]["child_pid"]
    process.kill()
    process.wait(timeout=5)
    wait_for(lambda: not status(root, "bot")["running"])
    assert f"stopped:{child}" in (root / "bot.events").read_text()


@pytest.mark.skipif(os.name != "nt", reason="Windows windowless entrypoint")
def test_windowless_web_process_uses_cooperative_shutdown(native_services):
    root, start = native_services
    process = start("web", windowless=True)
    child = status(root, "web")["record"]["child_pid"]
    request(root, "web", "pause")
    assert process.poll() is None
    assert f"stopped:{child}" in (root / "web.events").read_text()
    request(root, "web", "resume")
    wait_for(lambda: status(root, "web")["record"]["state"] == "running")
    assert status(root, "web")["record"]["child_pid"] != child


@pytest.mark.parametrize("lock_name", ["web.lock", "web.supervisor.lock"])
def test_service_start_waits_for_a_concurrent_status_probe(native_services, lock_name):
    root, start = native_services
    lease = Lease(root / "data/qqconf/services" / lock_name, create=True).acquire()

    def finish_observation():
        try:
            wait_for(lambda: (root / "web.events").exists())
            time.sleep(0.1)
        finally:
            lease.close()

    observer = threading.Thread(target=finish_observation)
    observer.start()
    try:
        process = start("web")
        assert process.poll() is None
        assert status(root, "web")["running"]
    finally:
        observer.join(timeout=20)


def test_control_record_writer_waits_until_the_reader_closes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from quickquip.configuration.process_control import _open_control, read_control, write_control

    path = tmp_path / "supervisor.json"
    write_control(path, {"state": "starting"})
    started, completed = threading.Event(), threading.Event()

    def publish():
        started.set()
        write_control(path, {"state": "running"})
        completed.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with _open_control(path) as reader:
            writer = pool.submit(publish)
            assert started.wait(2)
            assert not completed.wait(0.1)
            assert json.load(reader) == {"state": "starting"}
        writer.result(timeout=5)
    assert read_control(path) == {"state": "running"}
    assert read_control(tmp_path / "absent.json") is None
