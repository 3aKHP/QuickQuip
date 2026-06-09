from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ROOT_ENV_LOADED = False


def load_root_env_file() -> None:
    global _ROOT_ENV_LOADED
    if _ROOT_ENV_LOADED:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    _ROOT_ENV_LOADED = True


def load_project_env_files() -> None:
    load_root_env_file()
