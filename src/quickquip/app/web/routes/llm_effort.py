"""llm.toml provider 级 reasoning_effort 的结构化编辑（行级手术）。

配置文件没有 TOML round-trip 库可用，本模块在 tomllib 语义校验兜底下做最小
行级修改：只触碰目标 [[providers]] 块内的 reasoning_effort 行（缺省时在 id
行后插入），注释与其余块原样保留；块内出现多行字符串定界符时 fail-closed
拒绝，引导改用文本编辑。
"""

from __future__ import annotations

import logging
import re
import tomllib

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from quickquip.app.web.audit import audit_logger
from quickquip.app.web.routes.config import _CONFIG_FILES, _lock_for
from quickquip.common.paths import CONFIG_DIR
from quickquip.llm.config import REASONING_EFFORT_CHOICES

router = APIRouter()
logger = logging.getLogger(__name__)

_LLM_TOML = CONFIG_DIR / _CONFIG_FILES["llm"]["filename"]

_PROVIDERS_HEADER_RE = re.compile(r"^\s*\[\[providers\]\]\s*(?:#.*)?$")
_EFFORT_LINE_RE = re.compile(r"^\s*reasoning_effort\s*=")
# 既有档位行的安全改写形态：仅接受简单引号值，行尾注释随替换保留
_EFFORT_VALUE_RE = re.compile(
    r"^(\s*reasoning_effort\s*=\s*)(['\"])[^'\"]*\2(\s*(?:#.*)?)$"
)
# TOML 多行字符串定界符：块内出现时行级手术无法保证语义边界，拒绝写入
_MULTILINE_DELIMITERS = ('"""', "'''")


class EffortBody(BaseModel):
    # 必传（空 body 直接 422）；空串 = 删除该 provider 的 reasoning_effort 行
    #（回模型默认档，不发送思考参数）
    effort: str

    @field_validator("effort")
    @classmethod
    def _check_effort(cls, value: str) -> str:
        if value not in ("", *REASONING_EFFORT_CHOICES):
            raise ValueError(
                f"非法档位 {value!r}"
                f"（可用：{'/'.join(REASONING_EFFORT_CHOICES)}，留空回模型默认档）"
            )
        return value


def _project_providers(text: str) -> list[dict[str, str]]:
    """tomllib 解析后的 providers 投影；TOMLDecodeError 向上抛由调用方定状态码。"""
    data = tomllib.loads(text)
    raw = data.get("providers", [])
    if not isinstance(raw, list):
        raw = []
    providers: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        provider_id = str(entry.get("id", "")).strip()
        if not provider_id:
            continue
        providers.append({
            "id": provider_id,
            "default_model": str(entry.get("default_model", "")).strip(),
            "reasoning_effort": str(entry.get("reasoning_effort", "")).strip().lower(),
        })
    return providers


def _find_provider_block(lines: list[str], provider_id: str) -> tuple[int, int, int]:
    """定位目标 provider 的 [[providers]] 块。

    返回 (块起始行, 块结束行(不含), id 行下标)；块范围为 [[providers]] 行到
    下一个以 [ 开头的行（或文件尾）。找不到抛 404。
    """
    id_re = re.compile(r"^\s*id\s*=\s*(['\"])" + re.escape(provider_id) + r"\1\s*(?:#.*)?$")
    index = 0
    while index < len(lines):
        if not _PROVIDERS_HEADER_RE.match(lines[index]):
            index += 1
            continue
        end = index + 1
        while end < len(lines) and not lines[end].lstrip().startswith("["):
            end += 1
        for pos in range(index + 1, end):
            if id_re.match(lines[pos]):
                return index, end, pos
        index = end
    raise HTTPException(status_code=404, detail=f"provider {provider_id!r} 不存在")


def _apply_effort_edit(text: str, provider_id: str, effort: str) -> str:
    """对目标 provider 块做 reasoning_effort 行级手术，返回新文本（不落盘）。"""
    lines = text.split("\n")
    start, end, id_pos = _find_provider_block(lines, provider_id)
    if any(delim in line for line in lines[start:end] for delim in _MULTILINE_DELIMITERS):
        raise HTTPException(
            status_code=400, detail="该 provider 段含多行字符串，请用文本编辑"
        )
    effort_line_pos = next(
        (pos for pos in range(start + 1, end) if _EFFORT_LINE_RE.match(lines[pos])),
        None,
    )
    if effort == "":
        if effort_line_pos is not None:
            del lines[effort_line_pos]
    elif effort_line_pos is not None:
        match = _EFFORT_VALUE_RE.match(lines[effort_line_pos])
        if match is None:
            raise HTTPException(
                status_code=400,
                detail="既有 reasoning_effort 行形态无法安全改写，请用文本编辑",
            )
        lines[effort_line_pos] = f'{match.group(1)}"{effort}"{match.group(3)}'
    else:
        lines.insert(id_pos + 1, f'reasoning_effort = "{effort}"')
    return "\n".join(lines)


def _verify_edit(
    before: list[dict[str, str]],
    after: list[dict[str, str]],
    provider_id: str,
    effort: str,
) -> None:
    """手术后语义校验：provider 序列不变、目标档位符合意图、其余档位不动。"""
    if [p["id"] for p in after] != [p["id"] for p in before]:
        raise HTTPException(status_code=500, detail="手术后 provider 列表发生变化，已放弃写入")
    seen_target = False
    for old, new in zip(before, after, strict=True):
        if new["id"] == provider_id and not seen_target:
            seen_target = True
            if new["reasoning_effort"] != effort:
                raise HTTPException(
                    status_code=500, detail="手术后目标 provider 档位与意图不符，已放弃写入"
                )
            continue
        if new["reasoning_effort"] != old["reasoning_effort"]:
            raise HTTPException(
                status_code=500, detail="手术后其他 provider 档位发生变化，已放弃写入"
            )


@router.get("/llm-effort")
def get_llm_effort():
    if not _LLM_TOML.exists():
        raise HTTPException(status_code=404, detail="llm.toml 不存在")
    try:
        providers = _project_providers(_LLM_TOML.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise HTTPException(status_code=400, detail=f"llm.toml 解析失败：{e}")
    return {"providers": providers}


@router.put("/llm-effort/{provider_id}")
def put_llm_effort(provider_id: str, body: EffortBody, request: Request):
    effort = body.effort
    if not _LLM_TOML.exists():
        raise HTTPException(status_code=404, detail="llm.toml 不存在")
    tmp = _LLM_TOML.with_suffix(_LLM_TOML.suffix + ".tmp")
    # 读-手术-校验-落盘全程在锁内，避免与并发 PUT/文本编辑交错丢改
    with _lock_for(_LLM_TOML):
        original = _LLM_TOML.read_text(encoding="utf-8")
        try:
            before = _project_providers(original)
        except tomllib.TOMLDecodeError as e:
            raise HTTPException(status_code=400, detail=f"llm.toml 解析失败：{e}")
        if provider_id not in [p["id"] for p in before]:
            raise HTTPException(status_code=404, detail=f"provider {provider_id!r} 不存在")
        old_effort = next(p["reasoning_effort"] for p in before if p["id"] == provider_id)

        updated = _apply_effort_edit(original, provider_id, effort)

        try:
            after = _project_providers(updated)
        except tomllib.TOMLDecodeError as e:
            raise HTTPException(status_code=500, detail=f"手术后 TOML 解析失败，已放弃写入：{e}")
        _verify_edit(before, after, provider_id, effort)

        try:
            tmp.write_text(updated, encoding="utf-8")
            tmp.replace(_LLM_TOML)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    logger.warning(
        "llm reasoning_effort updated via web admin: %s %r -> %r",
        provider_id, old_effort, effort,
    )
    audit_logger.log(
        request,
        action="update",
        target_type="config",
        target_id="llm",
        summary_before={"provider": provider_id, "reasoning_effort": old_effort},
        summary_after={"provider": provider_id, "reasoning_effort": effort},
    )
    # 生效口径与 llm 裸文本编辑一致：引导手动 reload（见 routes/config.py put_config）
    return {"ok": True, "effect": "manual_reload"}
