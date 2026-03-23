from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import random
from time import time

from plugins.persistence import load_json, save_json


@dataclass(slots=True)
class TiebaThread:
    tid: str
    title: str
    thread_url: str
    author_name: str = ""
    main_post_text: str = ""
    cover_image_url: str = ""
    image_urls: list[str] = field(default_factory=list)
    fetched_at: float = 0.0
    last_seen_at: float = 0.0
    is_deleted: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "tid": self.tid,
            "title": self.title,
            "thread_url": self.thread_url,
            "author_name": self.author_name,
            "main_post_text": self.main_post_text,
            "cover_image_url": self.cover_image_url,
            "image_urls": list(self.image_urls),
            "fetched_at": self.fetched_at,
            "last_seen_at": self.last_seen_at,
            "is_deleted": self.is_deleted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TiebaThread":
        return cls(
            tid=str(data.get("tid", "")).strip(),
            title=str(data.get("title", "")).strip(),
            thread_url=str(data.get("thread_url", "")).strip(),
            author_name=str(data.get("author_name", "")).strip(),
            main_post_text=str(data.get("main_post_text", "")).strip(),
            cover_image_url=str(data.get("cover_image_url", "")).strip(),
            image_urls=[str(item).strip() for item in data.get("image_urls", []) if str(item).strip()],
            fetched_at=float(data.get("fetched_at", 0.0) or 0.0),
            last_seen_at=float(data.get("last_seen_at", 0.0) or 0.0),
            is_deleted=bool(data.get("is_deleted", False)),
        )


class TiebaStore:
    def __init__(
        self,
        path: str | Path,
        *,
        max_threads: int = 300,
        recent_sent_limit: int = 30,
    ):
        self.path = Path(path)
        self.max_threads = max_threads
        self.recent_sent_limit = recent_sent_limit
        self.forum_keyword = ""
        self.last_sync_started_at = 0.0
        self.last_sync_completed_at = 0.0
        self.last_sync_status = "idle"
        self.last_error = ""
        self.login_required = False
        self.threads: dict[str, TiebaThread] = {}
        self.recent_sent_ids: deque[str] = deque(maxlen=recent_sent_limit)

    def _looks_valid_thread(self, thread: TiebaThread) -> bool:
        title = thread.title.strip()
        content = thread.main_post_text.strip()
        if not thread.tid or not thread.thread_url or not title:
            return False
        if title.endswith("-百度贴吧"):
            return False
        noisy_markers = [
            "我常逛的吧",
            "我关注的吧",
            "展开全部",
            "首页 我的",
            "搬石 吧 发贴",
        ]
        if any(marker in content for marker in noisy_markers):
            return False
        return True

    def _sort_key(self, thread: TiebaThread) -> tuple[float, float, str]:
        return (-thread.last_seen_at, -thread.fetched_at, thread.tid)

    def load(self) -> None:
        data = load_json(self.path)
        if data is None:
            return

        self.forum_keyword = str(data.get("forum_keyword", "")).strip()
        self.last_sync_started_at = float(data.get("last_sync_started_at", 0.0) or 0.0)
        self.last_sync_completed_at = float(data.get("last_sync_completed_at", 0.0) or 0.0)
        self.last_sync_status = str(data.get("last_sync_status", "idle") or "idle").strip()
        self.last_error = str(data.get("last_error", "")).strip()
        self.login_required = bool(data.get("login_required", False))
        self.threads = {}
        for item in data.get("threads", []):
            if not isinstance(item, dict):
                continue
            thread = TiebaThread.from_dict(item)
            if self._looks_valid_thread(thread):
                self.threads[thread.tid] = thread

        recent_sent_ids = [
            str(item).strip()
            for item in data.get("recent_sent_ids", [])
            if str(item).strip()
        ]
        self.recent_sent_ids = deque(recent_sent_ids[-self.recent_sent_limit :], maxlen=self.recent_sent_limit)
        self._prune_threads()

    def save(self) -> None:
        data = {
            "forum_keyword": self.forum_keyword,
            "last_sync_started_at": self.last_sync_started_at,
            "last_sync_completed_at": self.last_sync_completed_at,
            "last_sync_status": self.last_sync_status,
            "last_error": self.last_error,
            "login_required": self.login_required,
            "recent_sent_ids": list(self.recent_sent_ids),
            "threads": [
                item.to_dict()
                for item in sorted(
                    self.threads.values(),
                    key=self._sort_key,
                )
            ],
        }
        save_json(self.path, data)

    def _prune_threads(self) -> None:
        if len(self.threads) <= self.max_threads:
            return
        sorted_threads = sorted(self.threads.values(), key=self._sort_key)
        self.threads = {thread.tid: thread for thread in sorted_threads[: self.max_threads]}

    def record_sync_started(self, forum_keyword: str, *, started_at: float | None = None) -> None:
        self.forum_keyword = forum_keyword.strip()
        self.last_sync_started_at = time() if started_at is None else started_at
        self.last_sync_status = "running"
        self.last_error = ""
        self.save()

    def record_sync_success(
        self,
        threads: list[TiebaThread],
        *,
        completed_at: float | None = None,
    ) -> int:
        current_ts = time() if completed_at is None else completed_at
        updated = 0
        for thread in threads:
            if not thread.tid or not thread.thread_url or not thread.title:
                continue
            existing = self.threads.get(thread.tid)
            if existing is None:
                merged = thread
            else:
                merged = TiebaThread(
                    tid=thread.tid,
                    title=thread.title or existing.title,
                    thread_url=thread.thread_url or existing.thread_url,
                    author_name=thread.author_name or existing.author_name,
                    main_post_text=thread.main_post_text or existing.main_post_text,
                    cover_image_url=thread.cover_image_url or existing.cover_image_url,
                    image_urls=thread.image_urls or existing.image_urls,
                    fetched_at=thread.fetched_at or current_ts,
                    last_seen_at=current_ts,
                    is_deleted=thread.is_deleted,
                )
            merged.last_seen_at = current_ts
            if not merged.fetched_at:
                merged.fetched_at = current_ts
            self.threads[thread.tid] = merged
            updated += 1

        self.threads = {
            tid: thread
            for tid, thread in self.threads.items()
            if self._looks_valid_thread(thread)
        }
        self._prune_threads()
        self.last_sync_completed_at = current_ts
        self.last_sync_status = "ok"
        self.last_error = ""
        self.login_required = False
        self.save()
        return updated

    def record_sync_failure(
        self,
        message: str,
        *,
        login_required: bool = False,
        failed_at: float | None = None,
    ) -> None:
        current_ts = time() if failed_at is None else failed_at
        self.last_sync_completed_at = current_ts
        self.last_sync_status = "login_required" if login_required else "error"
        self.last_error = message.strip()
        self.login_required = login_required
        self.save()

    def count(self) -> int:
        return len(self.threads)

    def list_threads(self) -> list[TiebaThread]:
        return sorted(
            self.threads.values(),
            key=self._sort_key,
        )

    def choose_random_thread(
        self,
        *,
        prefer_images: bool = True,
        avoid_recent: int = 10,
    ) -> TiebaThread | None:
        items = [
            thread
            for thread in self.threads.values()
            if not thread.is_deleted and self._looks_valid_thread(thread)
        ]
        if not items:
            return None

        recent_blocklist = set(list(self.recent_sent_ids)[-max(0, avoid_recent) :])
        available = [thread for thread in items if thread.tid not in recent_blocklist]
        if not available:
            available = items

        if prefer_images:
            with_image = [thread for thread in available if thread.cover_image_url or thread.image_urls]
            if with_image:
                available = with_image

        return random.choice(available) if available else None

    def mark_sent(self, tid: str) -> None:
        normalized_tid = tid.strip()
        if not normalized_tid:
            return
        self.recent_sent_ids.append(normalized_tid)
        self.save()
