import logging
import tomllib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from filelock import FileLock
from pydantic import BaseModel, Field

from quickquip.app.web.audit import audit_logger
from quickquip.app.web.settings import PROJECT_ROOT

router = APIRouter()
logger = logging.getLogger(__name__)

_CONFIG_DIR = PROJECT_ROOT / "config"
_MAX_CONTENT_BYTES = 65536

# Whitelist of editable root-level config files. Persona files live under
# config/personas/ and are served by the dedicated personas router.
_CONFIG_FILES: dict[str, dict] = {
    "llm": {
        "filename": "llm.toml",
        "label": "LLM 配置",
        "description": "文本对话模型、触发词、工具、MCP、人格装载",
    },
    "generation": {
        "filename": "generation.toml",
        "label": "多模态产出配置",
        "description": "图片与语音生成配置；后续视频产出也将归入这里",
    },
    "chat_rules": {
        "filename": "chat_rules.toml",
        "label": "聊天规则",
        "description": "文本规则、语境规则、限流与连锁游戏配置",
    },
}


class ConfigBody(BaseModel):
    content: str = Field(max_length=_MAX_CONTENT_BYTES)


def _resolve(key: str) -> Path:
    entry = _CONFIG_FILES.get(key)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown config key")
    return _CONFIG_DIR / entry["filename"]


def _lock_for(path: Path) -> FileLock:
    return FileLock(str(path) + ".lock")


@router.get("/config")
def list_configs():
    items = []
    for key, entry in _CONFIG_FILES.items():
        path = _CONFIG_DIR / entry["filename"]
        exists = path.exists()
        items.append({
            "key": key,
            "filename": entry["filename"],
            "label": entry["label"],
            "description": entry["description"],
            "exists": exists,
            "size": path.stat().st_size if exists else 0,
            "mtime": int(path.stat().st_mtime) if exists else 0,
        })
    return {"configs": items}


@router.get("/config/{key}")
def get_config(key: str):
    path = _resolve(key)
    if not path.exists():
        return {"key": key, "content": "", "missing": True}
    return {"key": key, "content": path.read_text(encoding="utf-8"), "missing": False}


@router.put("/config/{key}")
def put_config(key: str, body: ConfigBody, request: Request):
    path = _resolve(key)
    try:
        tomllib.loads(body.content)
    except tomllib.TOMLDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _lock_for(path):
        try:
            tmp.write_text(body.content, encoding="utf-8")
            tmp.replace(path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    logger.warning("config updated via web admin: %s (%d bytes)", key, len(body.content))
    audit_logger.log(
        request,
        action="update",
        target_type="config",
        target_id=key,
    )
    return {"ok": True}
