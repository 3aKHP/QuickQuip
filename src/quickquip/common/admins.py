"""全局管理员注册表与角色解析——权限判定的唯一真相源。

跨群只认 QQ 号，数据源 ``config/admins.toml``（TTL 节流 + mtime/size 戳
热重载）；群内角色照旧由 OneBot 事件的 ``sender.role`` 提供；私聊事件
（无 ``group_id``）恒 MEMBER。``has_admin_authority`` 为纯查询谓词；
``check_admin_authority`` 是唯一的门禁入口，全局身份越界时记审计。

审计（v1 轻量口径）：注册表加载/重载生效记 ``registry_loaded``（含名单，
服务器私有日志留痕授权面变更）；门禁经全局身份越过群角色边界放行时记
``global_admin_unlock``。群角色正常通过不记，避免噪音。
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
_GROUP_ADMIN_ROLES = ("admin", "owner")


def _emit_admin_trace(payload: dict) -> None:
    _logger.info(
        f"{_ADMIN_TRACE_MARK} {json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    )


def _sender_role(event) -> str | None:
    sender = getattr(event, "sender", None)
    return getattr(sender, "role", None) if sender is not None else None


class ActorRole(IntEnum):
    """有序角色。

    群管理档门禁请使用 :func:`has_admin_authority`（内含全局身份起效的
    审计）；直接比较 ``actor_role(event) >= ...`` 留给未来的更高档门禁，
    那些门禁需自带各自的审计口径。
    """

    MEMBER = 0
    GROUP_ADMIN = 1
    GROUP_OWNER = 2
    GLOBAL_ADMIN = 3


class AdminRegistry:
    """``config/admins.toml`` 的进程内缓存。

    调用节流（约 5s TTL）+ 文件 mtime/size 戳变更才重读；文件缺失与空表
    为合法的关闭态（清空并记 ``registry_loaded`` 留痕），解析失败保留上次
    有效名单。
    """

    def __init__(self, path: Path | str = CONFIG_ADMINS_TOML, clock=time.monotonic):
        self.path = Path(path)
        self._clock = clock
        self._lock = threading.RLock()
        self._admins: frozenset[str] = frozenset()
        self._last_check = float("-inf")
        self._stamp: tuple[int, int] | None = None
        self._failure_key: tuple | None = None

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
                stat = self.path.stat()
            except FileNotFoundError:
                stamp = None
            except OSError as exc:
                self._note_failure(("unstatable",), exc, "状态读取失败")
                return
            else:
                stamp = (stat.st_mtime_ns, stat.st_size)
            if stamp == self._stamp:
                return
            if stamp is None:
                admins = frozenset()
            else:
                try:
                    admins = self._parse()
                except Exception as exc:
                    self._note_failure(stamp, exc, "解析失败")
                    return
            self._admins = admins
            self._stamp = stamp
            self._failure_key = None
            _emit_admin_trace(
                {
                    "kind": "registry_loaded",
                    "count": len(admins),
                    "admins": sorted(admins),
                }
            )

    def _note_failure(self, key: tuple, exc: Exception, action: str) -> None:
        """同一失败形态只在首次记全栈 traceback，持续失败降为 warning。"""
        if key != self._failure_key:
            logger.exception("全局管理员配置%s，保留上次名单：%s", action, self.path)
        else:
            logger.warning("全局管理员配置%s（持续），保留上次名单：%s", action, self.path)
        self._failure_key = key

    def _parse(self) -> frozenset[str]:
        """解析注册表；坏文档抛异常由调用方保旧名单。"""
        raw = tomllib.loads(self.path.read_text(encoding="utf-8"))
        entries = raw.get("global_admins", [])
        if not isinstance(entries, list):
            raise ValueError("global_admins 须为字符串列表")
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
    """解析事件发起者的角色；先查全局注册表（双身份归 GLOBAL_ADMIN）。

    注册表命中仅对群聊事件生效（``group_id`` 缺失的私聊恒 MEMBER，
    与「私聊不放行」的 v1 语义一致）。
    """
    uid = str(getattr(event, "user_id", "") or "")
    if (
        uid
        and getattr(event, "group_id", None) is not None
        and uid in _registry().snapshot()
    ):
        return ActorRole.GLOBAL_ADMIN
    role = _sender_role(event)
    if role == "owner":
        return ActorRole.GROUP_OWNER
    if role == "admin":
        return ActorRole.GROUP_ADMIN
    return ActorRole.MEMBER


def has_admin_authority(event) -> bool:
    """纯查询谓词：管理员及以上（群主/群管/全局管理员），无副作用。"""
    return actor_role(event) >= ActorRole.GROUP_ADMIN


def check_admin_authority(event) -> bool:
    """门禁入口：结论与 :func:`has_admin_authority` 一致，全局身份越过
    群角色边界放行时记 ``global_admin_unlock`` 审计。"""
    role = actor_role(event)
    if role >= ActorRole.GLOBAL_ADMIN:
        _audit_global_unlock(event)
        return True
    return role >= ActorRole.GROUP_ADMIN


def _audit_global_unlock(event) -> None:
    """全局身份实际起效才记：群角色本就足够时全局身份没有越过边界。"""
    if _sender_role(event) in _GROUP_ADMIN_ROLES:
        return
    _emit_admin_trace(
        {
            "kind": "global_admin_unlock",
            "user_id": str(getattr(event, "user_id", "") or ""),
            "group_id": str(getattr(event, "group_id", "") or ""),
            "ts": time.time(),
        }
    )
