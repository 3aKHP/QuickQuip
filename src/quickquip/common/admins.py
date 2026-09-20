"""全局管理员注册表与角色解析——权限判定的唯一真相源。

跨群只认 QQ 号，数据源 ``config/admins.toml``（TTL 节流 + mtime/size 戳
热重载）；群内角色照旧由 OneBot 事件的 ``sender.role`` 提供；私聊事件无
群角色，恒 MEMBER。

审计（v1 轻量口径）：注册表加载/重载生效记 ``registry_loaded``（含名单，
服务器私有日志留痕授权面变更）；全局管理员身份实际起效（越过了群角色
边界）记 ``global_admin_unlock``。群角色正常通过不记，避免噪音。
"""
from __future__ import annotations

import json
import logging
import threading
import time
import tomllib
from enum import IntEnum
from pathlib import Path

from quickquip.common.paths import CONFIG_ADMINS_TOML
from quickquip.common.record_content import QQ

try:
    from loguru import logger as _logger
except ImportError:  # pragma: no cover - 环境兜底，与 bot_action_trace 同款
    _logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

_RELOAD_TTL_S = 5.0
_ADMIN_TRACE_MARK = "ADMIN_TRACE"


class ActorRole(IntEnum):
    """有序角色：门禁统一写法 ``actor_role(event) >= ActorRole.GROUP_ADMIN``。"""

    MEMBER = 0
    GROUP_ADMIN = 1
    GROUP_OWNER = 2
    GLOBAL_ADMIN = 3


class AdminRegistry:
    """``config/admins.toml`` 的进程内缓存。

    调用节流（约 5s TTL）+ 文件 mtime/size 戳变更才重读；文件缺失或解析
    失败时保留上次有效名单，缺失与空表均为合法的关闭态（行为与未启用一致）。
    """

    def __init__(self, path: Path | str = CONFIG_ADMINS_TOML, clock=time.monotonic):
        self.path = Path(path)
        self._clock = clock
        self._lock = threading.RLock()
        self._admins: frozenset[str] = frozenset()
        self._last_check = float("-inf")
        self._stamp: tuple[int, int] | None = None

    def contains(self, qq: str) -> bool:
        return str(qq) in self.snapshot()

    def snapshot(self) -> frozenset[str]:
        self._maybe_reload()
        with self._lock:
            return self._admins

    def _maybe_reload(self) -> None:
        now = self._clock()
        if now - self._last_check < _RELOAD_TTL_S:
            return
        with self._lock:
            if now - self._last_check < _RELOAD_TTL_S:
                return
            self._last_check = now
            try:
                stamp = (
                    (self.path.stat().st_mtime_ns, self.path.stat().st_size)
                    if self.path.exists()
                    else None
                )
            except OSError:
                logger.exception("全局管理员配置状态读取失败，保留上次名单：%s", self.path)
                return
            if stamp == self._stamp:
                return
            admins = self._load()
            if admins is None:
                return
            self._admins = admins
            self._stamp = stamp
            _logger.info(
                f"{_ADMIN_TRACE_MARK} "
                + json.dumps(
                    {
                        "kind": "registry_loaded",
                        "count": len(admins),
                        "admins": sorted(admins),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

    def _load(self) -> frozenset[str] | None:
        """解析注册表；返回 None 表示解析失败，调用方保留旧名单。"""
        try:
            raw = tomllib.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except Exception:
            logger.exception("全局管理员配置解析失败，保留上次名单：%s", self.path)
            return None
        entries = raw.get("global_admins", [])
        if not isinstance(entries, list):
            logger.error(
                "全局管理员配置 global_admins 须为字符串列表，保留上次名单：%s", self.path
            )
            return None
        valid: set[str] = set()
        for entry in entries:
            qq = str(entry).strip()
            if not QQ.fullmatch(qq):
                logger.warning("全局管理员条目非法（须为 QQ 号数字），已跳过：%r", entry)
                continue
            valid.add(qq)
        return frozenset(valid)


_registry_instance: AdminRegistry | None = None
_registry_module_lock = threading.Lock()


def _registry() -> AdminRegistry:
    global _registry_instance
    with _registry_module_lock:
        if _registry_instance is None:
            _registry_instance = AdminRegistry()
        return _registry_instance


def configure(path: Path | str) -> AdminRegistry:
    """替换默认注册表（测试注入与显式重置入口）。"""
    global _registry_instance
    with _registry_module_lock:
        _registry_instance = AdminRegistry(Path(path))
        return _registry_instance


def reset() -> None:
    """丢弃默认注册表缓存（测试隔离用；下次访问按生产路径重建）。"""
    global _registry_instance
    with _registry_module_lock:
        _registry_instance = None


def actor_role(event) -> ActorRole:
    """解析事件发起者的角色；先查全局注册表（双身份归 GLOBAL_ADMIN）。"""
    uid = str(getattr(event, "user_id", "") or "")
    if uid and uid in _registry().snapshot():
        return ActorRole.GLOBAL_ADMIN
    sender = getattr(event, "sender", None)
    role = getattr(sender, "role", None) if sender is not None else None
    if role == "owner":
        return ActorRole.GROUP_OWNER
    if role == "admin":
        return ActorRole.GROUP_ADMIN
    return ActorRole.MEMBER


def has_admin_authority(event) -> bool:
    """管理员及以上权限门禁（群主/群管/全局管理员）。"""
    role = actor_role(event)
    if role >= ActorRole.GLOBAL_ADMIN:
        _audit_global_unlock(event)
        return True
    return role >= ActorRole.GROUP_ADMIN


def _audit_global_unlock(event) -> None:
    """全局身份实际起效才记：群角色本就足够时全局身份没有越过边界。"""
    sender = getattr(event, "sender", None)
    role = getattr(sender, "role", None) if sender is not None else None
    if role in ("admin", "owner"):
        return
    _logger.info(
        f"{_ADMIN_TRACE_MARK} "
        + json.dumps(
            {
                "kind": "global_admin_unlock",
                "user_id": str(getattr(event, "user_id", "") or ""),
                "group_id": str(getattr(event, "group_id", "") or ""),
                "ts": time.time(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
