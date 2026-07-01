import logging
import tomllib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from filelock import FileLock
from pydantic import BaseModel, Field

from quickquip.app.web.audit import audit_logger
from quickquip.app.web.action_queue import action_queue
from quickquip.common.paths import CONFIG_DIR

router = APIRouter()
logger = logging.getLogger(__name__)

_CONFIG_DIR = CONFIG_DIR
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
    "games": {
        "filename": "games.toml",
        "label": "游戏配置",
        "description": "金币签到倍率、各游戏赌注/CD/超时等参数",
    },
    "awakening": {
        "filename": "awakening.toml",
        "label": "唤醒配置",
        "description": "按群唤醒延长、兴趣话题、相关性判定和无聊冒泡参数",
    },
    "niuniu_text": {
        "filename": "niuniu_text.toml",
        "label": "牛牛文案",
        "description": "牛牛大作战全部事件文案与长度评价",
    },
    "niuniu_text_safe": {
        "filename": "niuniu_text_safe.toml",
        "label": "牛牛文案（安全版）",
        "description": "牛牛大作战和谐版文案，仅覆写需要无害化的事件",
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
    if key == "awakening":
        action_queue.enqueue("awakening_reload")
        effect = "auto_reloading"
    elif key == "chat_rules":
        action_queue.enqueue("rules_reload")
        effect = "auto_reloading"
    elif key == "llm":
        # llm_reload 走 reload_runtime(background=True)，会触发 MCP 全量重连
        # （含容器/子进程重启），静默执行绕过用户感知；且 llm 配置影响面大
        # （provider/model/触发词/MCP），用户主动确认更稳妥，故引导手动 reload。
        # 注：reload_runtime 本身不探活（探活只在 /llm reload 命令路径），不涉及计费。
        effect = "manual_reload"
    else:
        # generation / games / niuniu_text* 无 reload 机制，需重启生效。
        effect = "restart_needed"
    return {"ok": True, "effect": effect}
