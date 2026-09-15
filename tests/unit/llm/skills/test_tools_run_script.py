"""run_skill_script 工具（tools/run_script.py）：子进程安全面。"""
from __future__ import annotations

import ast
import shutil

import pytest

from quickquip.llm.skills import (
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
    for bad in (0, -5, 120001):
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
    args = ("hello world", ";", "$(id)", "|", "&")
    result = await _run(skills, state, args=args)
    assert isinstance(result, LLMToolOutput)
    assert not result.is_error, result.content
    assert "退出码：0" in result.content
    for arg in args:
        assert arg in result.content  # 逐字传递，不经 shell 解释
    assert "[skill_script" in result.content


async def test_run_no_shell_substitution(make_skill):
    """shell 元语法作为字面参数原样到达脚本（无 shell 解释层）。"""
    catalog_dir, writer = make_skill
    writer("demo", files={"scripts/run.py": "import sys; print(sys.argv[1])\n"})
    skills, state, _ = _activated_env(catalog_dir, "demo")
    payload = "$(echo SHELL_WOULD_RUN_THIS)"
    result = await _run(skills, state, args=(payload,))
    assert payload in result.content
    assert "SHELL_WOULD_RUN_THIS\n" not in result.content.replace(payload, "")


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


async def test_run_cwd_is_skill_root(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", files={"scripts/run.py": _ARGV_DUMP_SCRIPT})
    skills, state, skill = _activated_env(catalog_dir, "demo")
    result = await _run(skills, state)
    assert not result.is_error, result.content
    import os

    expected = os.path.realpath(skill.root_dir)
    assert expected in result.content


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


async def test_run_py_no_shebang_or_exec_bit_needed(make_skill):
    """解释器映射不依赖 shebang/执行位：无执行位的 .py 照跑。"""
    catalog_dir, writer = make_skill
    root = writer("demo", files={"scripts/plain.py": "print('no-shebang-ok')\n"})
    script = root / "scripts" / "plain.py"
    script.chmod(0o644)
    skills, state, _ = _activated_env(catalog_dir, "demo")
    result = await _run(skills, state, path="scripts/plain.py")
    assert not result.is_error, result.content
    assert "no-shebang-ok" in result.content
