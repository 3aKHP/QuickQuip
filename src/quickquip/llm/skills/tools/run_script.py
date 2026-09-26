"""run_skill_script：执行已激活 Skill 的 scripts/ 目录下的脚本。

进程与安全面（与蓝本同源的结构性防御）：

- 结构化 argv 经 ``asyncio.create_subprocess_exec`` 启动，无 shell；
  参数逐字传递，不经任何解释层。
- 脚本不依赖 shebang 与执行位：按扩展名映射解释器（``.sh`` → ``sh``，
  ``.py`` → ``python3``，PATH 上找不到 ``python3`` 时回退当前解释器
  ``sys.executable``）。Windows 没有 ``sh`` 时 ``.sh`` 脚本 fail-closed
  报错；``.py`` 脚本因回退 ``sys.executable`` 而跨平台可跑。
- 执行前 SHA-256 快照复验：目录扫描时记录的脚本哈希与执行前现算的
  哈希不一致即拒绝执行。
- 子进程环境白名单仅 ``PATH``/``LANG``/``TZ``，不继承 bot 进程环境
  （``.env`` 凭证隔离）；cwd 固定为该 skill 目录。
- 墙钟超时（默认 ``script_timeout_ms``，硬上限 120000ms）与 stdout/stderr
  输出上限（``script_max_output_bytes``）：读取有界，超限即杀进程，
  内存占用不随脚本输出膨胀。POSIX 下脚本在独立进程组启动，终止按整组
  SIGKILL（孙进程一并清理）；工具调用被取消时同样杀进程组并排空管道，
  不留孤儿进程。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import signal
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from quickquip.llm.skills.catalog import (
    LoadedSkill,
    assert_safe_relative_path,
    classify_resource,
    resolve_skill_file,
)
from quickquip.llm.skills.state import SkillActivationState
from quickquip.llm.skills.tools.activate import require_active_skill
from quickquip.llm.tools import LLMToolOutput, LLMToolSpec

RUN_SKILL_SCRIPT_TOOL_NAME = "run_skill_script"

TOOL_DESCRIPTION = (
    "执行当前会话已激活 Skill 的 scripts/ 目录下的脚本（支持 .sh / .py，"
    "结构化参数、无 shell）。执行前校验脚本内容哈希；超时与输出大小受部署"
    "上限控制；脚本在隔离最小环境中运行（不继承机器人进程的环境变量），"
    "工作目录固定为该 Skill 目录。执行前应先用 read_skill_resource 查看"
    "脚本内容；不要用本工具跑与 Skill 无关的通用命令。"
)

TOOL_KEYWORDS = ["skill", "技能", "脚本", "执行", "运行", "script", "run", "命令"]

MAX_SCRIPT_TIMEOUT_MS = 120_000
_DEFAULT_OUTPUT_CHUNK = 65536
# 子进程环境白名单：仅这三个键（存在才传），其余一律不继承。
_ENV_WHITELIST = ("PATH", "LANG", "TZ")

RUN_SKILL_SCRIPT_SPEC = LLMToolSpec(
    name=RUN_SKILL_SCRIPT_TOOL_NAME,
    description=TOOL_DESCRIPTION,
    input_schema={
        "type": "object",
        "properties": {
            "skill": {"type": "string", "description": "已激活的 Skill 名。"},
            "path": {
                "type": "string",
                "description": "scripts/ 下的 skill 相对脚本路径。",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选参数列表，逐字传给脚本（不经 shell）。",
            },
            "timeout_ms": {
                "type": "integer",
                "description": f"墙钟超时毫秒数，默认取部署配置，上限 {MAX_SCRIPT_TIMEOUT_MS}。",
            },
        },
        "required": ["skill", "path"],
    },
)


async def run_skill_script(
    *,
    skill_name: str,
    path: str,
    script_args: Sequence[str] = (),
    timeout_ms: int | None = None,
    skills: Mapping[str, LoadedSkill],
    state: SkillActivationState,
    scope: str,
    default_timeout_ms: int = 30_000,
    max_output_bytes: int = 65_536,
) -> str | LLMToolOutput:
    resolved_skill = require_active_skill(skill_name, skills=skills, state=state, scope=scope)
    if isinstance(resolved_skill, LLMToolOutput):
        return resolved_skill
    skill = resolved_skill

    if any("\0" in arg for arg in script_args):
        return LLMToolOutput(content="args 不能包含 NUL 字节。", is_error=True)

    effective_timeout = timeout_ms if timeout_ms is not None else default_timeout_ms
    if effective_timeout < 1 or effective_timeout > MAX_SCRIPT_TIMEOUT_MS:
        return LLMToolOutput(
            content=f"timeout_ms 必须是 1 到 {MAX_SCRIPT_TIMEOUT_MS} 之间的整数。",
            is_error=True,
        )

    try:
        assert_safe_relative_path(path)
    except ValueError as exc:
        return LLMToolOutput(content=str(exc), is_error=True)
    if classify_resource(path) != "script":
        return LLMToolOutput(
            content=(
                f'Skill 路径 "{path}" 不是 scripts/ 下的脚本，不可执行；'
                "可用 read_skill_resource 读取。"
            ),
            is_error=True,
        )
    try:
        absolute = resolve_skill_file(skill, path)
    except ValueError as exc:
        return LLMToolOutput(content=str(exc), is_error=True)

    expected_hash = next(
        (resource.sha256 for resource in skill.resources if resource.path == path), ""
    )
    if not expected_hash:
        return LLMToolOutput(
            content=f'Skill 脚本 "{path}" 不在目录扫描清单中，未执行。',
            is_error=True,
        )
    try:
        actual_hash = hashlib.sha256(absolute.read_bytes()).hexdigest()
    except OSError as exc:
        return LLMToolOutput(
            content=f'无法在执行前校验脚本 "{path}"（{exc.strerror or exc}），未执行。',
            is_error=True,
        )
    if actual_hash != expected_hash:
        return LLMToolOutput(
            content=(
                f'Skill 脚本 "{path}" 的内容在目录扫描后已变化，未执行；'
                "请重新激活该 Skill 后再试。"
            ),
            is_error=True,
        )

    interpreter = _resolve_interpreter(path)
    if isinstance(interpreter, LLMToolOutput):
        return interpreter

    argv = [*interpreter, str(absolute), *script_args]
    env = {key: os.environ[key] for key in _ENV_WHITELIST if key in os.environ}

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=skill.root_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # POSIX：独立进程组（新 session），终止按整组 SIGKILL 清理孙进程。
            **({"start_new_session": True} if os.name == "posix" else {}),
        )
    except OSError as exc:
        return LLMToolOutput(
            content=f'无法启动解释器 "{Path(interpreter[0]).name}"：{exc.strerror or exc}',
            is_error=True,
        )

    output_cap = max(1, max_output_bytes)
    try:
        stdout, stderr, output_truncated = await asyncio.wait_for(
            _collect_output(process, output_cap),
            timeout=effective_timeout / 1000,
        )
        timed_out = False
    except TimeoutError:
        timed_out = True
        output_truncated = False
        _terminate_process(process)
        stdout, stderr = await _drain_after_kill(process, output_cap)
    except BaseException:
        # 取消/异常路径同样杀进程组并尽力排空管道，不留孤儿进程。
        _terminate_process(process)
        try:
            await asyncio.shield(_drain_after_kill(process, output_cap))
        except BaseException:
            pass
        raise

    exit_code = process.returncode
    sections = [
        f'[skill_script name="{skill.name}" path="{path}" '
        f'interpreter="{Path(interpreter[0]).name}"]',
        f"stdout:\n{stdout}" if stdout else "stdout: (empty)",
        f"stderr:\n{stderr}" if stderr else "stderr: (empty)",
    ]
    if output_truncated:
        sections.append(f"[输出超过 {output_cap} 字节上限，已截断]")
    if timed_out:
        sections.append(f"脚本运行超过 {effective_timeout} ms，已被终止。")
    else:
        sections.append(f"退出码：{exit_code}")
    ok = not timed_out and exit_code == 0
    return LLMToolOutput(content="\n\n".join(sections), is_error=not ok)


def _resolve_interpreter(path: str) -> list[str] | LLMToolOutput:
    """扩展名 → 解释器 argv 前缀；不支持的扩展名 fail-closed 列出受支持项。"""
    base = path.rsplit("/", 1)[-1]
    dot = base.rfind(".")
    extension = base[dot:].lower() if dot > 0 else ""
    if extension == ".py":
        command = shutil.which("python3") or sys.executable
        return [command]
    if extension == ".sh":
        command = shutil.which("sh")
        if command is None:
            return LLMToolOutput(
                content=(
                    f'运行 "{path}" 需要 sh，但当前进程 PATH 上找不到；'
                    "脚本未执行（Windows 主机请改用 .py 脚本）。"
                ),
                is_error=True,
            )
        return [command]
    return LLMToolOutput(
        content=(
            f'不支持 "{extension or path}" 类型的脚本；受支持的扩展名：.py、.sh。'
        ),
        is_error=True,
    )


def _terminate_process(process: asyncio.subprocess.Process) -> None:
    """终止脚本进程：POSIX 下整组 SIGKILL（孙进程一并清理），其余平台杀直接子进程。"""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass  # 终止判定与进程自然退出撞车：无需再杀


async def _collect_output(process: asyncio.subprocess.Process, cap: int) -> tuple[str, str, bool]:
    """有界收集 stdout/stderr：超过 cap 即杀进程并排空管道到 EOF（丢弃超额
    部分），保证传输层正常关闭；返回解码文本与截断标记。"""

    async def _read(stream: asyncio.StreamReader | None) -> bytes:
        if stream is None:
            return b""
        chunks: list[bytes] = []
        total = 0
        over = False
        while True:
            chunk = await stream.read(_DEFAULT_OUTPUT_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > cap and process.returncode is None:
                _terminate_process(process)
            if over:
                continue
            chunks.append(chunk)
            if total > cap:
                over = True
        return b"".join(chunks)

    stdout_task = asyncio.ensure_future(_read(process.stdout))
    stderr_task = asyncio.ensure_future(_read(process.stderr))
    stdout_raw, stderr_raw = await asyncio.gather(stdout_task, stderr_task)
    truncated = len(stdout_raw) > cap or len(stderr_raw) > cap
    await process.wait()
    return (
        _decode_capped(stdout_raw, cap),
        _decode_capped(stderr_raw, cap),
        truncated,
    )


async def _drain_after_kill(
    process: asyncio.subprocess.Process, cap: int
) -> tuple[str, str]:
    """超时杀进程后排空管道残余输出（有界截断，忽略读取异常）。"""
    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(process.communicate(), timeout=5)
    except Exception:
        return "", ""
    return _decode_capped(stdout_raw, cap), _decode_capped(stderr_raw, cap)


def _decode_capped(raw: bytes, cap: int) -> str:
    if len(raw) > cap:
        raw = raw[:cap]
    return raw.decode("utf-8", errors="replace")
