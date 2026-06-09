from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import random
from time import time
from typing import Iterable

from quickquip.common.persistence import load_json, save_json
from quickquip.tieba.config import normalize_forum_keyword


@dataclass(slots=True)
class TiebaThread:
    tid: str
    title: str
    thread_url: str
    forum_keyword: str = ""
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
            "forum_keyword": self.forum_keyword,
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
            forum_keyword=normalize_forum_keyword(str(data.get("forum_keyword", ""))),
            author_name=str(data.get("author_name", "")).strip(),
            main_post_text=str(data.get("main_post_text", "")).strip(),
            cover_image_url=str(data.get("cover_image_url", "")).strip(),
            image_urls=[str(item).strip() for item in data.get("image_urls", []) if str(item).strip()],
            fetched_at=float(data.get("fetched_at", 0.0) or 0.0),
            last_seen_at=float(data.get("last_seen_at", 0.0) or 0.0),
            is_deleted=bool(data.get("is_deleted", False)),
        )


@dataclass(slots=True)
class TiebaForumState:
    forum_keyword: str
    last_sync_started_at: float = 0.0
    last_sync_completed_at: float = 0.0
    last_sync_status: str = "idle"
    last_error: str = ""
    login_required: bool = False
    threads: dict[str, TiebaThread] = field(default_factory=dict)
    recent_sent_ids: deque[str] = field(default_factory=deque)

    def to_dict(self) -> dict[str, object]:
        return {
            "forum_keyword": self.forum_keyword,
            "last_sync_started_at": self.last_sync_started_at,
            "last_sync_completed_at": self.last_sync_completed_at,
            "last_sync_status": self.last_sync_status,
            "last_error": self.last_error,
            "login_required": self.login_required,
            "recent_sent_ids": list(self.recent_sent_ids),
            "threads": [thread.to_dict() for thread in self.threads.values()],
        }


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
        self.forums: dict[str, TiebaForumState] = {}

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

    def _sort_key(self, thread: TiebaThread) -> tuple[float, float, str, str]:
        return (-thread.last_seen_at, -thread.fetched_at, thread.forum_keyword, thread.tid)

    def _new_recent_sent_ids(self, values: Iterable[str] | None = None) -> deque[str]:
        normalized = [str(item).strip() for item in values or [] if str(item).strip()]
        return deque(normalized[-self.recent_sent_limit :], maxlen=self.recent_sent_limit)

    def _ensure_state(self, forum_keyword: str) -> TiebaForumState:
        normalized = normalize_forum_keyword(forum_keyword)
        if not normalized:
            raise ValueError("forum_keyword cannot be empty")
        state = self.forums.get(normalized)
        if state is not None:
            return state
        state = TiebaForumState(
            forum_keyword=normalized,
            recent_sent_ids=self._new_recent_sent_ids(),
        )
        self.forums[normalized] = state
        return state

    def get_forum_state(self, forum_keyword: str) -> TiebaForumState | None:
        return self.forums.get(normalize_forum_keyword(forum_keyword))

    def list_forum_keywords(self) -> list[str]:
        return sorted(self.forums)

    def set_recent_sent_limit(self, recent_sent_limit: int) -> None:
        self.recent_sent_limit = max(1, recent_sent_limit)
        for state in self.forums.values():
            state.recent_sent_ids = self._new_recent_sent_ids(state.recent_sent_ids)

    def _prune_threads(self, state: TiebaForumState) -> None:
        if len(state.threads) <= self.max_threads:
            return
        sorted_threads = sorted(state.threads.values(), key=self._sort_key)
        state.threads = {thread.tid: thread for thread in sorted_threads[: self.max_threads]}

    def _load_forum_state(self, data: dict[str, object]) -> None:
        forum_keyword = normalize_forum_keyword(str(data.get("forum_keyword", "")))
        if not forum_keyword:
            return

        state = TiebaForumState(
            forum_keyword=forum_keyword,
            last_sync_started_at=float(data.get("last_sync_started_at", 0.0) or 0.0),
            last_sync_completed_at=float(data.get("last_sync_completed_at", 0.0) or 0.0),
            last_sync_status=str(data.get("last_sync_status", "idle") or "idle").strip(),
            last_error=str(data.get("last_error", "")).strip(),
            login_required=bool(data.get("login_required", False)),
            recent_sent_ids=self._new_recent_sent_ids(data.get("recent_sent_ids", [])),
        )

        for item in data.get("threads", []):
            if not isinstance(item, dict):
                continue
            thread = TiebaThread.from_dict(item)
            if not thread.forum_keyword:
                thread.forum_keyword = forum_keyword
            if self._looks_valid_thread(thread):
                state.threads[thread.tid] = thread

        self._prune_threads(state)
        self.forums[forum_keyword] = state

    def load(self) -> None:
        data = load_json(self.path)
        if data is None:
            return

        self.forums = {}
        if isinstance(data.get("forums", []), list):
            for item in data.get("forums", []):
                if isinstance(item, dict):
                    self._load_forum_state(item)
            return

        self._load_forum_state(data)

    def save(self) -> None:
        data = {
            "forums": [
                {
                    **state.to_dict(),
                    "threads": [
                        item.to_dict()
                        for item in sorted(state.threads.values(), key=self._sort_key)
                    ],
                }
                for _, state in sorted(self.forums.items())
            ]
        }
        save_json(self.path, data)

    def record_sync_started(self, forum_keyword: str, *, started_at: float | None = None) -> None:
        state = self._ensure_state(forum_keyword)
        state.last_sync_started_at = time() if started_at is None else started_at
        state.last_sync_status = "running"
        state.last_error = ""
        self.save()

    def record_sync_success(
        self,
        forum_keyword: str,
        threads: list[TiebaThread],
        *,
        completed_at: float | None = None,
    ) -> int:
        state = self._ensure_state(forum_keyword)
        current_ts = time() if completed_at is None else completed_at
        updated = 0
        normalized_forum = state.forum_keyword
        for thread in threads:
            if not thread.tid or not thread.thread_url or not thread.title:
                continue
            existing = state.threads.get(thread.tid)
            if existing is None:
                merged = thread
            else:
                merged = TiebaThread(
                    tid=thread.tid,
                    title=thread.title or existing.title,
                    thread_url=thread.thread_url or existing.thread_url,
                    forum_keyword=normalized_forum,
                    author_name=thread.author_name or existing.author_name,
                    main_post_text=thread.main_post_text or existing.main_post_text,
                    cover_image_url=thread.cover_image_url or existing.cover_image_url,
                    image_urls=thread.image_urls or existing.image_urls,
                    fetched_at=thread.fetched_at or current_ts,
                    last_seen_at=current_ts,
                    is_deleted=thread.is_deleted,
                )
            merged.forum_keyword = normalized_forum
            merged.last_seen_at = current_ts
            if not merged.fetched_at:
                merged.fetched_at = current_ts
            state.threads[thread.tid] = merged
            updated += 1

        state.threads = {
            tid: thread
            for tid, thread in state.threads.items()
            if self._looks_valid_thread(thread)
        }
        self._prune_threads(state)
        state.last_sync_completed_at = current_ts
        state.last_sync_status = "ok"
        state.last_error = ""
        state.login_required = False
        self.save()
        return updated

    def record_sync_failure(
        self,
        forum_keyword: str,
        message: str,
        *,
        login_required: bool = False,
        failed_at: float | None = None,
    ) -> None:
        state = self._ensure_state(forum_keyword)
        current_ts = time() if failed_at is None else failed_at
        state.last_sync_completed_at = current_ts
        state.last_sync_status = "login_required" if login_required else "error"
        state.last_error = message.strip()
        state.login_required = login_required
        self.save()

    def _selected_states(self, forum_keywords: Iterable[str] | None = None) -> list[TiebaForumState]:
        if forum_keywords is None:
            return list(self.forums.values())

        selected: list[TiebaForumState] = []
        seen: set[str] = set()
        for item in forum_keywords:
            forum_keyword = normalize_forum_keyword(item)
            if not forum_keyword or forum_keyword in seen:
                continue
            seen.add(forum_keyword)
            state = self.forums.get(forum_keyword)
            if state is not None:
                selected.append(state)
        return selected

    def count(self, forum_keywords: Iterable[str] | None = None) -> int:
        return sum(len(state.threads) for state in self._selected_states(forum_keywords))

    def list_threads(self, forum_keywords: Iterable[str] | None = None) -> list[TiebaThread]:
        items: list[TiebaThread] = []
        for state in self._selected_states(forum_keywords):
            items.extend(state.threads.values())
        return sorted(items, key=self._sort_key)

    def any_login_required(self, forum_keywords: Iterable[str] | None = None) -> bool:
        return any(state.login_required for state in self._selected_states(forum_keywords))

    def choose_random_thread(
        self,
        *,
        forum_keywords: Iterable[str] | None = None,
        prefer_images: bool = True,
        avoid_recent: int = 10,
    ) -> TiebaThread | None:
        available: list[TiebaThread] = []
        for state in self._selected_states(forum_keywords):
            items = [
                thread
                for thread in state.threads.values()
                if not thread.is_deleted and self._looks_valid_thread(thread)
            ]
            if not items:
                continue

            recent_blocklist = set(list(state.recent_sent_ids)[-max(0, avoid_recent) :])
            filtered = [thread for thread in items if thread.tid not in recent_blocklist]
            available.extend(filtered or items)

        if not available:
            return None

        if prefer_images:
            with_image = [thread for thread in available if thread.cover_image_url or thread.image_urls]
            if with_image:
                available = with_image

        return random.choice(available) if available else None

    def mark_sent(self, tid: str, forum_keyword: str | None = None) -> None:
        normalized_tid = tid.strip()
        if not normalized_tid:
            return

        state: TiebaForumState | None = None
        if forum_keyword:
            state = self.get_forum_state(forum_keyword)
        else:
            for candidate in self.forums.values():
                if normalized_tid in candidate.threads:
                    state = candidate
                    break

        if state is None:
            return
        state.recent_sent_ids.append(normalized_tid)
        self.save()
