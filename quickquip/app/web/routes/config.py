import logging
import tomllib
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)

# 基于文件位置的绝对路径，不依赖进程工作目录
# __file__ = quickquip/app/web/routes/config.py
# parents[4] = 项目根目录
_CONFIG_PATH = Path(__file__).parents[4] / "config" / "llm.toml"


class ConfigBody(BaseModel):
    content: str = Field(max_length=65536)


@router.get("/config/llm")
def get_llm_config():
    if not _CONFIG_PATH.exists():
        return {"content": "", "missing": True}
    return {"content": _CONFIG_PATH.read_text(encoding="utf-8"), "missing": False}


@router.put("/config/llm")
def put_llm_config(body: ConfigBody):
    try:
        tomllib.loads(body.content)
    except tomllib.TOMLDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 原子写入：先写临时文件，再 rename，避免写入中途崩溃产生损坏文件
    tmp = _CONFIG_PATH.with_suffix(".toml.tmp")
    tmp.write_text(body.content, encoding="utf-8")
    tmp.replace(_CONFIG_PATH)
    logger.warning("llm.toml updated via web admin (%d bytes)", len(body.content))
    return {"ok": True}
