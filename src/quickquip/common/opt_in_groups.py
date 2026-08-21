"""opt-in 群集合的 JSON 持久化（``{"enabled": [...]}`` schema）。

daily_summary / daily_briefing / period_report / awakening_boredom 四个开关
共享同一不变量：启用某功能的群集合以 JSON 文件持久化。本模块是唯一实现，
各领域以薄子类声明自己的默认路径与群号归一化策略。

不变量：
- 写入：FileLock（``<path>.lock``）互斥下先重读磁盘、合并修改，再
  tmp+replace 原子落盘——bot 进程（命令路径）与 Web Admin 进程交叉写入
  不丢更新。
- 读取：缺文件保持现状（视为空）；坏 JSON / OSError 回退为空集合。
- 序列化：``{"enabled": sorted(...)}``，UTF-8，``ensure_ascii=False``，
  ``indent=2``。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from filelock import FileLock

logger = logging.getLogger(__name__)


def normalize_digit_group_id(group_id: int | str) -> str:
    """严格群号归一化：去空白后必须全为数字，否则抛 ValueError。

    仅用于群号场景。私聊会话标识（``private:USER_ID``，由
    ``LLMService.build_chat_scope_key`` 派生）不是全数字，不得走本函数；
    本模块只承载"群 opt-in 集合"不变量，与私聊 scope_key 无关。
    """
    s = str(group_id).strip()
    if not s.isdigit():
        raise ValueError(f"Invalid group_id (must be all digits): {group_id!r}")
    return s


class OptInGroupSet:
    """``{"enabled": [...]}`` JSON 持久化的 opt-in 群集合。

    子类可覆盖 ``log_label``（日志标识）、``_normalize_group_id``
    （写入侧群号归一化）与 ``_load_entry``（读取侧条目归一化，返回
    None 表示跳过该条目）。
    """

    log_label = "opt_in_groups"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._groups: set[str] = set()
        self.load()

    def _normalize_group_id(self, group_id: int | str) -> str:
        return str(group_id)

    def _load_entry(self, raw: object) -> str | None:
        return str(raw)

    def _lock(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self.path) + ".lock")

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._groups = set()
            return
        groups: set[str] = set()
        for raw in data.get("enabled", []):
            entry = self._load_entry(raw)
            if entry is not None:
                groups.add(entry)
        self._groups = groups

    def save(self) -> None:
        with self._lock():
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to a temp file then rename to avoid corruption on crash
        tmp = self.path.with_suffix(".json.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump({"enabled": sorted(self._groups)}, f, ensure_ascii=False, indent=2)
            tmp.replace(self.path)
        except OSError:
            logger.warning("%s: failed to save enabled groups to %s", self.log_label, self.path)
            tmp.unlink(missing_ok=True)

    def add(self, group_id: int | str) -> None:
        gid = self._normalize_group_id(group_id)
        with self._lock():
            # 锁内重读磁盘再合并：另一进程（Web Admin / bot）的写入不被覆盖
            self.load()
            self._groups.add(gid)
            self._save_unlocked()

    def remove(self, group_id: int | str) -> None:
        gid = self._normalize_group_id(group_id)
        with self._lock():
            self.load()
            self._groups.discard(gid)
            self._save_unlocked()

    def set_enabled(self, group_id: int | str, enabled: bool) -> bool:
        """锁内读取-修改-写入并返回变更前状态（供审计日志取准确的 before 值）。"""
        gid = self._normalize_group_id(group_id)
        with self._lock():
            self.load()
            old = gid in self._groups
            if enabled:
                self._groups.add(gid)
            else:
                self._groups.discard(gid)
            self._save_unlocked()
        return old

    def contains(self, group_id: int | str) -> bool:
        return self._normalize_group_id(group_id) in self._groups

    def all_groups(self) -> list[str]:
        return sorted(self._groups)
