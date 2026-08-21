"""MCP lifecycle mixin: client sync, background startup, shutdown, tool re-registration.

Extracted from ``tools.py`` (v1.12.1 P9) so the MCP connection lifecycle —
dirty tracking, the background startup task, shutdown drain, and re-registering
MCP tool aliases into the tool registry — has a single owner, separate from
builtin tool declarations, discovery policy, and tool handlers.

MRO contract: McpLifecycleMixin reads only host-owned public attributes —
``self.mcp_manager``, ``self.config``, ``self.tool_registry`` (all initialised
in ``LLMService.__init__``) — plus its own ``self._mcp_*`` state, initialised
by ``_init_mcp_lifecycle()`` (mirroring the ``_init_auto_memory()`` precedent).
It never reaches into another mixin's private state; other mixins and the host
must go through the public methods (``ensure_mcp_ready`` / ``startup`` /
``shutdown`` / ``reload_mcp`` / ``start_mcp_background``) instead of touching
``self._mcp_*``.
"""
from __future__ import annotations

import asyncio
import logging

from quickquip.llm.tools import LLMToolSpec

logger = logging.getLogger(__name__)


class McpLifecycleMixin:
    def _init_mcp_lifecycle(self) -> None:
        self._mcp_tool_names: set[str] = set()
        self._mcp_dirty = True
        self._mcp_lock = asyncio.Lock()
        self._mcp_startup_task: asyncio.Task[None] | None = None

    def _clear_mcp_tools(self) -> None:
        for name in self._mcp_tool_names:
            self.tool_registry.unregister(name)
        self._mcp_tool_names.clear()

    def _register_mcp_tools(self) -> None:
        self._clear_mcp_tools()
        for binding in self.mcp_manager.bindings.values():
            async def _handler(arguments, context, *, alias=binding.alias):
                return await self.mcp_manager.execute(alias, arguments, context)

            self.tool_registry.register(
                LLMToolSpec(
                    name=binding.alias,
                    description=f"[MCP/{binding.server_id}] {binding.description}",
                    input_schema=binding.input_schema,
                ),
                _handler,
                source=f"mcp:{binding.server_id}",
                category=f"mcp:{binding.server_id}",
                keywords=[binding.server_id, binding.tool_name, "mcp"],
            )
            self._mcp_tool_names.add(binding.alias)

    async def ensure_mcp_ready(self, force: bool = False, force_pull: bool = False) -> None:
        async with self._mcp_lock:
            if not force and not self._mcp_dirty:
                return
            await self.mcp_manager.sync(self.config.mcp, force_pull=force_pull)
            self._register_mcp_tools()
            self._mcp_dirty = False

    def _is_mcp_initializing(self) -> bool:
        return self._mcp_startup_task is not None and not self._mcp_startup_task.done()

    async def _run_mcp_startup(self, force: bool, force_pull: bool = False) -> None:
        try:
            await self.ensure_mcp_ready(force=force, force_pull=force_pull)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MCP background startup failed")
        finally:
            self._mcp_startup_task = None

    def start_mcp_background(self, force: bool = False, force_pull: bool = False) -> None:
        if self._is_mcp_initializing():
            return
        self._mcp_startup_task = asyncio.create_task(
            self._run_mcp_startup(force=force, force_pull=force_pull),
            name="quickquip-mcp-startup",
        )

    async def startup(self, *, background: bool = False) -> None:
        if background:
            self.start_mcp_background(force=True)
            return
        await self.ensure_mcp_ready(force=True)

    async def shutdown(self) -> None:
        if self._mcp_startup_task is not None:
            self._mcp_startup_task.cancel()
            await asyncio.gather(self._mcp_startup_task, return_exceptions=True)
            self._mcp_startup_task = None
        await self.mcp_manager.aclose()

    async def reload_mcp(self, *, background: bool = False) -> None:
        """重连所有 MCP 服务器，对 docker transport 强制 pull 最新镜像。"""
        self._mcp_dirty = True
        if background:
            self.start_mcp_background(force=True, force_pull=True)
            return
        await self.ensure_mcp_ready(force=True, force_pull=True)
