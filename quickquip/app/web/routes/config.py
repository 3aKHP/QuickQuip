import tomllib
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_CONFIG_PATH = Path("config/llm.toml")


class ConfigBody(BaseModel):
    content: str


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
    _CONFIG_PATH.write_text(body.content, encoding="utf-8")
    return {"ok": True}
