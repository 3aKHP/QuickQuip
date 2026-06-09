from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def _find_project_root() -> Path:
    """Locate the project root.

    Walk up from this file looking for a marker that exists in every layout:
    the src layout (repo-root/src/quickquip/...), the hybrid container mount
    (/app/src/quickquip/...), and the flattened Windows lazy package
    (staging/quickquip/...). When the package is pip-installed into
    site-packages with no source tree above it (the no-mount Docker fallback),
    no marker is found, so fall back to the working directory — which is the
    project root in every runtime entrypoint (bot.py, web_api.py, pytest), the
    same invariant the cwd-relative paths in paths.py already rely on.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "bot.py").exists() or (parent / "config").is_dir():
            return parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()
_ROOT_ENV_LOADED = False


def load_root_env_file() -> None:
    global _ROOT_ENV_LOADED
    if _ROOT_ENV_LOADED:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    _ROOT_ENV_LOADED = True


def load_project_env_files() -> None:
    load_root_env_file()
