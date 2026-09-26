"""run_skill_script 工具（tools/run_script.py）：子进程安全面。"""
from __future__ import annotations

import ast
import asyncio
import os
import shutil

import pytest

from quickquip.llm.skills import (
    MAX_SCRIPT_TIMEOUT_MS,
    SkillActivationState,
    run_skill_script,
    scan_skills,
)
from quickquip.llm.tools import LLMToolOutput

from tests.unit.llm.skills.conftest import load_single

_SCOPE = "s1"

_ARGV_DUMP_SCRIPT = (
    "import json, os, sys\n"
    "print(json.dumps(sys.argv[1:]))\n"
    "print(sorted(os.environ.keys()))\n"
    "print(os.path.realpath(os.getcwd()))\n"
)


def _activated_env(catalog_dir, name: str):
    skill = load_single(catalog_dir, name)
    state = SkillActivationState()
    state.record(_SCOPE, name, skill.body_sha256)
    return {name: skill}, state, skill


async def _run(skills, state, name="demo", path="scripts/run.py", args=(), **kwargs):
    return await run_skill_script(
        skill_name=name,
        path=path,
        script_args=args,
        skills=skills,
        state=state,
        scope=_SCOPE,
        **kwargs,
    )


# ── 门与参数校验 ─────────────────────────────────────────────────


async def test_run_gates(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"scripts/run.py": "print(1)\n"})
    skills = {skill.name: skill for skill in scan_skills(catalog_dir)}

    missing = await _run(skills, SkillActivationState(), name="ghost")
    assert isinstance(missing, LLMToolOutput) and missing.is_error
    assert "未安装" in missing.content

    inactive = await _run(skills, SkillActivationState())
    assert isinstance(inactive, LLMToolOutput) and inactive.is_error
    assert "尚未在当前会话激活" in inactive.content


async def test_run_rejects_nul_in_args(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"scripts/run.py": "print(1)\n"})
    skills, state, _ = _activated_env(catalog_dir, "demo")
    result = await _run(skills, state, args=("a\0b",))
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "NUL" in result.content


async def test_run_timeout_range_validation(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"scripts/run.py": "print(1)\n"})
    skills, state, _ = _activated_env(catalog_dir, "demo")
    for bad in (0, -5, MAX_SCRIPT_TIMEOUT_MS + 1):
        result = await _run(skills, state, timeout_ms=bad)
        assert isinstance(result, LLMToolOutput) and result.is_error, bad
        assert "timeout_ms" in result.content


async def test_run_rejects_non_scripts_path(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"references/run.py": "print(1)\n"})
    skills, state, _ = _activated_env(catalog_dir, "demo")
    result = await _run(skills, state, path="references/run.py")
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "不是 scripts/ 下的脚本" in result.content


async def test_run_rejects_unsafe_path(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"scripts/run.py": "print(1)\n"})
    skills, state, _ = _activated_env(catalog_dir, "demo")
    for bad in ("../x.py", "/abs/x.py", "scripts\\run.py"):
        result = await _run(skills, state, path=bad)
        assert isinstance(result, LLMToolOutput) and result.is_error, bad


async def test_run_rejects_unknown_extension(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"scripts/notes.txt": "x"})
    skills, state, _ = _activated_env(catalog_dir, "demo")
    result = await _run(skills, state, path="scripts/notes.txt")
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "受支持的扩展名" in result.content


async def test_run_rejects_script_not_in_scan_listing(make_skill):
    """扫描后落盘的脚本不在哈希清单中，拒绝执行。"""
    catalog_dir, writer = make_skill
    root = writer("demo")
    skills, state, _ = _activated_env(catalog_dir, "demo")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "late.py").write_text("print(1)\n", encoding="utf-8")
    result = await _run(skills, state, path="scripts/late.py")
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "不在目录扫描清单中" in result.content


async def test_run_rejects_tampered_script(make_skill):
    """SHA-256 复验：扫描快照与执行前现算不一致即拒绝。"""
    catalog_dir, writer = make_skill
    root = writer("demo", files={"scripts/run.py": "print('v1')\n"})
    skills, state, _ = _activated_env(catalog_dir, "demo")
    (root / "scripts" / "run.py").write_text("print('v2 篡改')\n", encoding="utf-8")
    result = await _run(skills, state)
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "已变化" in result.content
    assert "v2 篡改" not in result.content


# ── 正常执行 ─────────────────────────────────────────────────────


async def test_run_py_success_and_literal_args(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"scripts/run.py": _ARGV_DUMP_SCRIPT})
    skills, state, skill = _activated_env(catalog_dir, "demo")
    (skill.root_dir / "scripts" / "run.py").chmod(0o644)
    args = ("hello world", ";", "$(id)", "|", "&")
    result = await _run(skills, state, args=args)
    assert isinstance(result, LLMToolOutput)
    assert not result.is_error, result.content
    assert os.path.realpath(skill.root_dir) in result.content
    assert "退出码：0" in result.content
    for arg in args:
        assert arg in result.content  # 逐字传递，不经 shell 解释
    assert "[skill_script" in result.content
    # marker 只嵌解释器 basename，不泄漏主机绝对路径
    marker_line = result.content.splitlines()[0]
    interpreter_name = marker_line.rsplit('interpreter="', 1)[1].removesuffix('"]')
    assert "/" not in interpreter_name
    assert "\\" not in interpreter_name


async def test_run_env_whitelist(make_skill, monkeypatch):
    """子进程环境 = {PATH, LANG, TZ} 白名单；bot 进程的涉密变量不泄漏。"""
    monkeypatch.setenv("QQ_SECRET_TOKEN", "top-secret-value")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    catalog_dir, writer = make_skill
    writer("demo", files={"scripts/run.py": _ARGV_DUMP_SCRIPT})
    skills, state, _ = _activated_env(catalog_dir, "demo")
    result = await _run(skills, state)
    assert not result.is_error, result.content
    env_line = next(
        line for line in result.content.splitlines() if line.startswith("['")
    )
    child_keys = set(ast.literal_eval(env_line))  # 子进程打印的 sorted(list) 字面量
    assert child_keys <= {"PATH", "LANG", "TZ"}
    assert "QQ_SECRET_TOKEN" not in child_keys
    assert "top-secret-value" not in result.content
    assert "sk-test-secret" not in result.content


async def test_run_nonzero_exit_is_error(make_skill):
    catalog_dir, writer = make_skill
    writer(
        "demo",
        files={"scripts/run.py": "import sys; sys.stderr.write(' boom\\n'); sys.exit(3)\n"},
    )
    skills, state, _ = _activated_env(catalog_dir, "demo")
    result = await _run(skills, state)
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "退出码：3" in result.content
    assert " boom" in result.content


async def test_run_timeout_kills_process(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"scripts/run.py": "import time; time.sleep(30)\n"})
    skills, state, _ = _activated_env(catalog_dir, "demo")
    result = await _run(skills, state, timeout_ms=800)
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "已被终止" in result.content
    assert "800 ms" in result.content


async def _wait_file(path, rounds=100):
    for _ in range(rounds):
        if path.exists():
            return True
        await asyncio.sleep(0.05)
    return False


async def _assert_pid_dead(pid: int) -> None:
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"进程 {pid} 仍存活")


@pytest.mark.skipif(os.name != "posix", reason="进程存活探测依赖 POSIX kill(0)")
async def test_run_cancellation_kills_process(make_skill):
    """工具调用被取消：杀脚本进程并排空管道，不留孤儿。"""
    catalog_dir, writer = make_skill
    writer(
        "demo",
        files={
            "scripts/run.py": (
                "import os, pathlib, time\n"
                "pathlib.Path('pid.txt').write_text(str(os.getpid()))\n"
                "time.sleep(30)\n"
            )
        },
    )
    skills, state, skill = _activated_env(catalog_dir, "demo")
    run_task = asyncio.create_task(_run(skills, state))
    pid_path = skill.root_dir / "pid.txt"
    assert await _wait_file(pid_path), "脚本未能及时启动"
    pid = int(pid_path.read_text())
    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task
    await _assert_pid_dead(pid)


@pytest.mark.skipif(os.name != "posix", reason="进程组语义为 POSIX 专属")
async def test_run_timeout_kills_whole_process_group(make_skill):
    """POSIX：脚本在独立进程组启动，超时按整组 SIGKILL，孙进程一并清理。"""
    catalog_dir, writer = make_skill
    writer(
        "demo",
        files={
            "scripts/run.py": (
                "import os, pathlib, subprocess, sys, time\n"
                "grandchild = subprocess.Popen(\n"
                "    [sys.executable, '-c', 'import time; time.sleep(30)']\n"
                ")\n"
                "pathlib.Path('pids.txt').write_text(f'{os.getpid()} {grandchild.pid}')\n"
                "time.sleep(30)\n"
            )
        },
    )
    skills, state, skill = _activated_env(catalog_dir, "demo")
    run_task = asyncio.create_task(_run(skills, state, timeout_ms=800))
    pids_path = skill.root_dir / "pids.txt"
    assert await _wait_file(pids_path), "脚本未能及时启动"
    result = await run_task
    assert isinstance(result, LLMToolOutput) and result.is_error
    assert "已被终止" in result.content
    parent_pid, grandchild_pid = (int(part) for part in pids_path.read_text().split())
    await _assert_pid_dead(parent_pid)
    await _assert_pid_dead(grandchild_pid)


async def test_run_output_truncation(make_skill):
    catalog_dir, writer = make_skill
    writer(
        "demo",
        files={"scripts/run.py": "print('x' * 200000)\n"},
    )
    skills, state, _ = _activated_env(catalog_dir, "demo")
    result = await _run(skills, state, max_output_bytes=1000)
    assert isinstance(result, LLMToolOutput)
    assert "已截断" in result.content
    stdout_section = result.content.split("stdout:\n", 1)[1].split("\n\n", 1)[0]
    assert len(stdout_section) <= 1100  # cap + 解码余量


@pytest.mark.skipif(shutil.which("sh") is None, reason="sh 不在 PATH 上")
async def test_run_sh_script(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"scripts/run.sh": "echo shell-ok\n"})
    skills, state, _ = _activated_env(catalog_dir, "demo")
    result = await _run(skills, state, path="scripts/run.sh")
    assert isinstance(result, LLMToolOutput)
    assert not result.is_error, result.content
    assert "shell-ok" in result.content


class _FakeDrainProc:
    """只实现 communicate() 的假进程：钉住 drain 截断行为（确定性单测）。"""

    async def communicate(self):
        return b"A" * 5000, b"B" * 5000


async def test_drain_after_kill_caps_output():
    """超时杀进程后的排空解码同样受 output cap 截断（Deep-CR L2-NV1）。"""
    from quickquip.llm.skills.tools.run_script import _drain_after_kill

    stdout, stderr, truncated = await _drain_after_kill(_FakeDrainProc(), cap=1024)
    assert stdout == "A" * 1024
    assert stderr == "B" * 1024
    assert truncated is True
