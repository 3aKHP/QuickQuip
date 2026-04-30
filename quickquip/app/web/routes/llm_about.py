import logging
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from filelock import FileLock
from pydantic import BaseModel, Field

from quickquip.app.web.settings import PROJECT_ROOT
from quickquip.llm.identity import IdentityIndex
from quickquip.llm.vocab import VocabIndex

router = APIRouter()
logger = logging.getLogger(__name__)

_LLM_ABOUT_DIR = PROJECT_ROOT / "llm_about"
_GROUP_RE = re.compile(r"^\d{5,12}$")
_KINDS = {
    "vocab": {
        "filename": "vocab.yaml",
        "label": "词表",
        "description": "群成员称呼、别名和群内黑话",
    },
    "identities": {
        "filename": "identities.yaml",
        "label": "身份",
        "description": "QQ 号到标准身份的映射",
    },
}
_VOCAB_SECTIONS = {"核心成员", "次核心成员", "次核心成员追加", "部分黑话解析"}
_MAX_CONTENT_BYTES = 131072


class LLMAboutContent(BaseModel):
    content: str = Field(max_length=_MAX_CONTENT_BYTES)


class LLMAboutGroupCreate(BaseModel):
    group_id: str = Field(min_length=5, max_length=12)
    copy_example: bool = True


def _validate_scope(scope: str) -> None:
    if scope == "global":
        return
    if not _GROUP_RE.match(scope):
        raise HTTPException(status_code=422, detail="scope must be global or a 5-12 digit group id")


def _validate_kind(kind: str) -> None:
    if kind not in _KINDS:
        raise HTTPException(status_code=404, detail="unknown llm_about file kind")


def _scope_dir(scope: str) -> Path:
    _validate_scope(scope)
    if scope == "global":
        return _LLM_ABOUT_DIR
    return _LLM_ABOUT_DIR / scope


def _resolve(scope: str, kind: str) -> Path:
    _validate_kind(kind)
    return _scope_dir(scope) / _KINDS[kind]["filename"]


def _lock_for(path: Path) -> FileLock:
    return FileLock(str(path) + ".lock")


def _file_meta(scope: str, kind: str) -> dict:
    path = _resolve(scope, kind)
    exists = path.exists()
    return {
        "scope": scope,
        "kind": kind,
        "filename": _KINDS[kind]["filename"],
        "label": _KINDS[kind]["label"],
        "description": _KINDS[kind]["description"],
        "path": f"llm_about/{_KINDS[kind]['filename']}" if scope == "global" else f"llm_about/{scope}/{_KINDS[kind]['filename']}",
        "exists": exists,
        "size": path.stat().st_size if exists else 0,
        "mtime": int(path.stat().st_mtime) if exists else 0,
    }


def _validate_vocab_content(content: str) -> None:
    if not content.strip():
        return
    sections = {
        line.split(":", 1)[0].strip()
        for line in content.splitlines()
        if line and not line.startswith(" ") and ":" in line
    }
    if not sections.intersection(_VOCAB_SECTIONS):
        raise HTTPException(status_code=400, detail="vocab.yaml must contain a known vocab section")

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            prefix="quickquip.vocab.validate.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(content)
        VocabIndex.from_file(tmp_path)
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def _validate_identities_content(content: str) -> None:
    if not content.strip():
        return
    sections = {
        line.split(":", 1)[0].strip()
        for line in content.splitlines()
        if line and not line.startswith(" ") and ":" in line
    }
    if not sections.intersection({"people", "special_accounts"}):
        raise HTTPException(status_code=400, detail="identities.yaml must contain people or special_accounts")

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            prefix="quickquip.identities.validate.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(content)
        IdentityIndex.from_file(tmp_path)
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def _validate_content(kind: str, content: str) -> None:
    if kind == "vocab":
        _validate_vocab_content(content)
        return
    if kind == "identities":
        _validate_identities_content(content)
        return
    _validate_kind(kind)


def _copy_example_file(scope_dir: Path, kind: str) -> None:
    filename = _KINDS[kind]["filename"]
    target = scope_dir / filename
    if target.exists():
        return
    source = _LLM_ABOUT_DIR / "_example" / filename
    content = source.read_text(encoding="utf-8") if source.exists() else ""
    target.write_text(content, encoding="utf-8")


@router.get("/llm-about")
def list_llm_about():
    global_files = [_file_meta("global", kind) for kind in _KINDS]
    scopes: list[dict] = [
        {
            "scope": "global",
            "label": "全局资料",
            "global": True,
            "path": "llm_about/",
            "files": global_files,
            "existing_files": sum(1 for item in global_files if item["exists"]),
            "total_files": len(global_files),
        }
    ]

    if _LLM_ABOUT_DIR.exists():
        for path in sorted(_LLM_ABOUT_DIR.iterdir()):
            if not path.is_dir() or not _GROUP_RE.match(path.name):
                continue
            files = [_file_meta(path.name, kind) for kind in _KINDS]
            scopes.append({
                "scope": path.name,
                "label": path.name,
                "global": False,
                "path": f"llm_about/{path.name}/",
                "files": files,
                "existing_files": sum(1 for item in files if item["exists"]),
                "total_files": len(files),
            })

    return {
        "base_path": str(_LLM_ABOUT_DIR),
        "scopes": scopes,
        "kinds": [{"kind": kind, **meta} for kind, meta in _KINDS.items()],
    }


@router.get("/llm-about/{scope}/{kind}")
def get_llm_about_file(scope: str, kind: str):
    path = _resolve(scope, kind)
    if not path.exists():
        return {"scope": scope, "kind": kind, "content": "", "missing": True}
    return {"scope": scope, "kind": kind, "content": path.read_text(encoding="utf-8"), "missing": False}


@router.put("/llm-about/{scope}/{kind}")
def put_llm_about_file(scope: str, kind: str, body: LLMAboutContent):
    path = _resolve(scope, kind)
    _validate_content(kind, body.content)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _lock_for(path):
        try:
            tmp.write_text(body.content, encoding="utf-8")
            tmp.replace(path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    logger.warning("llm_about updated via web admin: %s/%s (%d bytes)", scope, kind, len(body.content))
    return {"ok": True}


@router.post("/llm-about/groups", status_code=201)
def create_llm_about_group(body: LLMAboutGroupCreate):
    group_id = body.group_id.strip()
    if not _GROUP_RE.match(group_id):
        raise HTTPException(status_code=422, detail="group_id must be 5-12 digits")

    target_dir = _LLM_ABOUT_DIR / group_id
    target_dir.mkdir(parents=True, exist_ok=True)
    if body.copy_example:
        for kind in _KINDS:
            _copy_example_file(target_dir, kind)

    logger.warning("llm_about group scope created via web admin: %s", group_id)
    return {"scope": group_id, "files": [_file_meta(group_id, kind) for kind in _KINDS]}
