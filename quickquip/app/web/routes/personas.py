import logging
import re
import tomllib
from pathlib import Path

from fastapi import APIRouter, HTTPException
from filelock import FileLock
from pydantic import BaseModel, Field

from quickquip.app.web.settings import PROJECT_ROOT

router = APIRouter()
logger = logging.getLogger(__name__)

_PERSONAS_DIR = PROJECT_ROOT / "config" / "personas"
_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]{0,63}$")
_PROTECTED_NAMES = {"_shared"}
_MAX_CONTENT_BYTES = 65536


class PersonaContent(BaseModel):
    content: str = Field(max_length=_MAX_CONTENT_BYTES)


class PersonaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    content: str = Field(max_length=_MAX_CONTENT_BYTES)


def _validate_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=422, detail="persona name must match [A-Za-z0-9_][A-Za-z0-9_-]{0,63}")


def _persona_path(name: str) -> Path:
    _validate_name(name)
    return _PERSONAS_DIR / f"{name}.toml"


def _lock_for(path: Path) -> FileLock:
    return FileLock(str(path) + ".lock")


def _parse_meta(text: str) -> dict:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    return {
        "id": data.get("id"),
        "display_name": data.get("display_name"),
        "source": data.get("source"),
        "scope": data.get("scope"),
    }


@router.get("/personas")
def list_personas():
    if not _PERSONAS_DIR.exists():
        return {"personas": []}
    items = []
    for path in sorted(_PERSONAS_DIR.iterdir()):
        if not path.is_file() or path.suffix != ".toml":
            continue
        name = path.stem
        if not _NAME_RE.match(name):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        stat = path.stat()
        meta = _parse_meta(text)
        items.append({
            "name": name,
            "display_name": meta.get("display_name"),
            "id": meta.get("id"),
            "source": meta.get("source"),
            "scope": meta.get("scope"),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "protected": name in _PROTECTED_NAMES,
        })
    return {"personas": items}


@router.get("/personas/{name}")
def get_persona(name: str):
    path = _persona_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="persona not found")
    return {"name": name, "content": path.read_text(encoding="utf-8")}


@router.put("/personas/{name}")
def update_persona(name: str, body: PersonaContent):
    path = _persona_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="persona not found")
    try:
        tomllib.loads(body.content)
    except tomllib.TOMLDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    tmp = path.with_suffix(".toml.tmp")
    with _lock_for(path):
        try:
            tmp.write_text(body.content, encoding="utf-8")
            tmp.replace(path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    logger.warning("persona updated via web admin: %s (%d bytes)", name, len(body.content))
    return {"ok": True}


@router.post("/personas", status_code=201)
def create_persona(body: PersonaCreate):
    _validate_name(body.name)
    if body.name in _PROTECTED_NAMES:
        raise HTTPException(status_code=409, detail="reserved persona name")
    path = _persona_path(body.name)
    if path.exists():
        raise HTTPException(status_code=409, detail="persona already exists")
    try:
        tomllib.loads(body.content)
    except tomllib.TOMLDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    with _lock_for(path):
        try:
            tmp.write_text(body.content, encoding="utf-8")
            tmp.replace(path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    logger.warning("persona created via web admin: %s (%d bytes)", body.name, len(body.content))
    return {"name": body.name}


@router.delete("/personas/{name}")
def delete_persona(name: str):
    _validate_name(name)
    if name in _PROTECTED_NAMES:
        raise HTTPException(status_code=409, detail="protected persona cannot be deleted")
    path = _persona_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="persona not found")
    with _lock_for(path):
        path.unlink()
    logger.warning("persona deleted via web admin: %s", name)
    return {"ok": True}
