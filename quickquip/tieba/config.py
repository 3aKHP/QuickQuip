from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
from urllib import parse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from quickquip.chat.config import BEIJING_TIMEZONE


TIEBA_RULE_NAME = "tieba_random_post"
DATA_DIR = Path("data/tieba")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORE_PATH = DATA_DIR / "pool.json"
PROFILE_DIR = DATA_DIR / "profile"
STATE_PATH = DATA_DIR / "storage_state.json"
DEFAULT_SYNC_INTERVAL_SECONDS = 900
DEFAULT_MAX_POOL_SIZE = 240
DEFAULT_RECENT_SENT_LIMIT = 30
DEFAULT_DETAIL_FETCH_LIMIT = 18
DEFAULT_RANDOM_AVOID_RECENT = 10


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def normalize_forum_keyword(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized.endswith("吧") and len(normalized) > 1:
        return normalized[:-1].strip()
    return normalized


def load_project_env_files() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(PROJECT_ROOT / "dev/.env", override=True)


def clean_text(value: str, *, limit: int = 0) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if limit > 0:
        return normalized[:limit]
    return normalized


def clean_thread_title(value: str) -> str:
    normalized = clean_text(value, limit=120)
    if normalized.endswith("-百度贴吧"):
        normalized = normalized[: -len("-百度贴吧")].rstrip()
    return normalized


def format_timestamp(timestamp: float) -> str:
    if timestamp <= 0:
        return "未记录"
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo(BEIJING_TIMEZONE))
    return dt.strftime("%Y-%m-%d %H:%M")


@dataclass(slots=True)
class TiebaConfig:
    enabled: bool
    forum_keyword: str
    sync_interval_seconds: int
    max_pool_size: int
    recent_sent_limit: int
    detail_fetch_limit: int
    random_avoid_recent: int
    prefer_image_threads: bool
    browser_headless: bool
    browser_channel: str
    profile_dir: Path
    state_path: Path
    store_path: Path

    @property
    def forum_url(self) -> str:
        encoded_kw = parse.quote(self.forum_keyword)
        return f"https://tieba.baidu.com/f?kw={encoded_kw}"

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.forum_keyword)


def load_tieba_config() -> TiebaConfig:
    load_project_env_files()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return TiebaConfig(
        enabled=env_bool("TIEBA_ENABLED", False),
        forum_keyword=normalize_forum_keyword(os.getenv("TIEBA_FORUM_KEYWORD", "")),
        sync_interval_seconds=max(
            60,
            int(os.getenv("TIEBA_SYNC_INTERVAL_SECONDS", DEFAULT_SYNC_INTERVAL_SECONDS) or DEFAULT_SYNC_INTERVAL_SECONDS),
        ),
        max_pool_size=max(
            20,
            int(os.getenv("TIEBA_MAX_POOL_SIZE", DEFAULT_MAX_POOL_SIZE) or DEFAULT_MAX_POOL_SIZE),
        ),
        recent_sent_limit=max(
            1,
            int(os.getenv("TIEBA_RECENT_SENT_LIMIT", DEFAULT_RECENT_SENT_LIMIT) or DEFAULT_RECENT_SENT_LIMIT),
        ),
        detail_fetch_limit=max(
            1,
            int(os.getenv("TIEBA_DETAIL_FETCH_LIMIT", DEFAULT_DETAIL_FETCH_LIMIT) or DEFAULT_DETAIL_FETCH_LIMIT),
        ),
        random_avoid_recent=max(
            0,
            int(os.getenv("TIEBA_RANDOM_AVOID_RECENT", DEFAULT_RANDOM_AVOID_RECENT) or DEFAULT_RANDOM_AVOID_RECENT),
        ),
        prefer_image_threads=env_bool("TIEBA_PREFER_IMAGE_THREADS", True),
        browser_headless=env_bool("TIEBA_BROWSER_HEADLESS", True),
        browser_channel=os.getenv("TIEBA_BROWSER_CHANNEL", "").strip(),
        profile_dir=PROFILE_DIR,
        state_path=STATE_PATH,
        store_path=STORE_PATH,
    )
