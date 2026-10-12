"""Task leases over published configuration and MCP resource generations."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps

from quickquip.llm.config import LLMConfig
from quickquip.llm.mcp import MCPClientManager
from quickquip.llm.tool_registry import ToolRegistry


@dataclass(eq=False)
class RuntimeResources:
    manager: MCPClientManager
    registry: ToolRegistry
    mcp_names: set[str] = field(default_factory=set)
    dirty: bool = True
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    startup_task: asyncio.Task | None = None
    leases: int = 0
    retired: bool = False
    closed: bool = False
    drained: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self):
        self.drained.set()


@dataclass(eq=False)
class RuntimeSnapshot:
    config: LLMConfig
    resources: RuntimeResources
    image_preprocessor: object = None


@dataclass
class TaskToolBindings:
    owner: object
    registry: ToolRegistry
    skills: dict
    skill_tools_registered: bool
    skill_registered_names: list[str]


_TASK_TOOLS: ContextVar[TaskToolBindings | None] = ContextVar("quickquip_task_tools", default=None)


_LEASE: ContextVar[tuple[object, RuntimeSnapshot] | None] = ContextVar(
    "quickquip_configuration_lease", default=None
)
_REQUEST_PROVIDER: ContextVar[tuple[object, object] | None] = ContextVar(
    "quickquip_request_provider", default=None
)


def current_snapshot(owner) -> RuntimeSnapshot | None:
    lease = _LEASE.get()
    return lease[1] if lease is not None and lease[0] is owner else None


def snapshot_entry(method):
    """Pin all service reads through nested tools and asynchronous billing."""
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        async with self.configuration_lease():
            return await method(self, *args, **kwargs)
    return wrapped


def chat_model_entry(method):
    @wraps(method)
    async def wrapped(self, request):
        async with self.configuration_lease():
            if self.config.load_error or self.store is None:
                return await method(self, request)
            from quickquip.llm.config_document import resolve_model_provider
            settings = self.get_chat_settings(request.chat_id, chat_type=request.chat_type)
            try:
                provider = resolve_model_provider(self.config, settings.provider_id, settings.model)
            except ValueError:
                provider = None
            token = _REQUEST_PROVIDER.set((self, provider))
            try:
                return await method(self, request)
            finally:
                _REQUEST_PROVIDER.reset(token)
    return wrapped


def leased_service(get_service):
    """Adapter/job entry with an injected service getter."""
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            service = get_service(*args, **kwargs)
            if hasattr(service, "configuration_lease"):
                async with service.configuration_lease():
                    return await function(*args, **kwargs)
            return await function(*args, **kwargs)
        return wrapped
    return decorate


class RuntimeSnapshotMixin:
    def effective_request_provider(self, provider_id):
        entry = _REQUEST_PROVIDER.get()
        if entry is not None and entry[0] is self:
            provider = entry[1]
            if provider is not None and provider.id == provider_id:
                return provider
        return self.config.providers.get(provider_id)

    def _init_configuration_leases(self):
        self._configuration_gate = asyncio.Lock()
        self._configuration_stopping = False
        self._configuration_fenced = False
        self._configuration_boot_check = None
        self._retired_resources: set[RuntimeResources] = set()
        self._resource_cleanup_tasks: set[asyncio.Task] = set()
        self._runtime_snapshot = RuntimeSnapshot(
            self._config, RuntimeResources(self._mcp_manager, self._tool_registry),
            self._image_preprocessor,
        )

    def _snapshot(self):
        return current_snapshot(self) or getattr(self, "_runtime_snapshot", None)

    @property
    def config(self):
        if current_snapshot(self) is None:
            checker = getattr(self, "_configuration_boot_check", None)
            if checker is not None:
                try:
                    checker()
                except Exception:
                    self.fence_configuration_runtime()
                    raise
        snapshot = self._snapshot()
        return snapshot.config if snapshot is not None else self._config

    @config.setter
    def config(self, value):
        # Assignment creates a new view; active leases keep their old view.
        snapshot = getattr(self, "_runtime_snapshot", None)
        self._config = value
        if snapshot is not None:
            self._runtime_snapshot = RuntimeSnapshot(
                value, snapshot.resources, snapshot.image_preprocessor
            )

    @property
    def mcp_manager(self):
        snapshot = self._snapshot()
        return snapshot.resources.manager if snapshot is not None else self._mcp_manager

    @mcp_manager.setter
    def mcp_manager(self, value):
        self._mcp_manager = value
        snapshot = self._snapshot()
        if snapshot is not None:
            snapshot.resources.manager = value

    @property
    def tool_registry(self):
        binding = _TASK_TOOLS.get()
        if binding is not None and binding.owner is self:
            return binding.registry
        snapshot = self._snapshot()
        return snapshot.resources.registry if snapshot is not None else self._tool_registry

    @tool_registry.setter
    def tool_registry(self, value):
        self._tool_registry = value
        snapshot = self._snapshot()
        if snapshot is not None:
            snapshot.resources.registry = value

    @property
    def image_preprocessor(self):
        snapshot = self._snapshot()
        return snapshot.image_preprocessor if snapshot is not None else self._image_preprocessor

    @image_preprocessor.setter
    def image_preprocessor(self, value):
        self._image_preprocessor = value
        snapshot = self._snapshot()
        if snapshot is not None:
            snapshot.image_preprocessor = value

    @contextmanager
    def configuration_view(self, snapshot):
        """Prepare resources or scheduler descriptions with an explicit view."""
        previous = current_snapshot(self)
        token = _LEASE.set((self, snapshot))
        tools_token = _TASK_TOOLS.set(None) if previous is not snapshot else None
        try:
            yield snapshot
        finally:
            _LEASE.reset(token)
            if tools_token is not None:
                _TASK_TOOLS.reset(tools_token)

    @asynccontextmanager
    async def configuration_lease(self):
        # Lightweight degraded/test hosts retain the same entry contract.
        if not hasattr(self, "_runtime_snapshot"):
            from quickquip.llm.usage import configuration_pricing
            with configuration_pricing(self.config):
                yield self.config
            return
        async with self._configuration_gate:
            if self._configuration_fenced and current_snapshot(self) is None:
                from quickquip.llm.config_errors import ConfigError
                raise ConfigError(
                    "runtime_superseded", "A newer bot boot owns configuration control"
                )
            if self._configuration_stopping and current_snapshot(self) is None:
                raise RuntimeError("LLM configuration runtime is shutting down")
            if current_snapshot(self) is None and self._configuration_boot_check is not None:
                try:
                    self._configuration_boot_check()
                except Exception:
                    self.fence_configuration_runtime()
                    raise
            snapshot = current_snapshot(self) or self._runtime_snapshot
            snapshot.resources.leases += 1
            snapshot.resources.drained.clear()
        from quickquip.llm.usage import configuration_pricing
        try:
            with self.configuration_view(snapshot), configuration_pricing(snapshot.config):
                existing = _TASK_TOOLS.get()
                tools_token = None
                if existing is None or existing.owner is not self:
                    tools_token = _TASK_TOOLS.set(TaskToolBindings(
                        self, snapshot.resources.registry.fork(),
                        dict(getattr(self, "_initial_skill_catalog", {})),
                        getattr(self, "_initial_skill_registered", False),
                        list(getattr(self, "_initial_skill_names", [])),
                    ))
                try:
                    yield snapshot.config
                finally:
                    if tools_token is not None:
                        _TASK_TOOLS.reset(tools_token)
        finally:
            snapshot.resources.leases -= 1
            if snapshot.resources.leases == 0:
                snapshot.resources.drained.set()
            self._release_retired(snapshot.resources)

    def _release_retired(self, resources):
        if resources.retired and resources.leases == 0 and not resources.closed:
            resources.closed = True
            task = asyncio.create_task(self._close_resources(resources))
            self._resource_cleanup_tasks.add(task)
            task.add_done_callback(self._resource_cleanup_tasks.discard)

    def create_configuration_task(self, coroutine):
        """Reserve the parent lease before scheduling a background child."""
        snapshot = self._snapshot()
        if snapshot is None:
            return asyncio.create_task(coroutine)
        snapshot.resources.leases += 1
        snapshot.resources.drained.clear()
        tools = _TASK_TOOLS.get()

        async def run():
            from quickquip.llm.usage import configuration_pricing
            try:
                with self.configuration_view(snapshot), configuration_pricing(snapshot.config):
                    token = _TASK_TOOLS.set(tools)
                    try:
                        return await coroutine
                    finally:
                        _TASK_TOOLS.reset(token)
            finally:
                snapshot.resources.leases -= 1
                if snapshot.resources.leases == 0:
                    snapshot.resources.drained.set()
                self._release_retired(snapshot.resources)
        return asyncio.create_task(run())

    async def _close_resources(self, resources):
        if resources.startup_task is not None:
            resources.startup_task.cancel()
            await asyncio.gather(resources.startup_task, return_exceptions=True)
        await resources.manager.aclose()
        self._retired_resources.discard(resources)

    def prepare_configuration(self, config, *, force_mcp=False):
        old = self._runtime_snapshot
        resources = old.resources
        if force_mcp or old.config.mcp != config.mcp:
            resources = RuntimeResources(MCPClientManager(), ToolRegistry())
        snapshot = RuntimeSnapshot(config, resources)
        with self.configuration_view(snapshot):
            if resources is not old.resources:
                self._register_builtin_tools()
                self.register_skill_tools()
            self.rebuild_image_preprocessor()
        return snapshot

    def activate_configuration(self, snapshot):
        old = self._runtime_snapshot
        self._runtime_snapshot = snapshot
        self._config = snapshot.config
        if old.resources is not snapshot.resources:
            old.resources.retired = True
            self._retired_resources.add(old.resources)
            self._release_retired(old.resources)

    def fence_configuration_runtime(self):
        """Stop new work; tasks with a pre-existing lease may finish."""
        self._configuration_fenced = True
        self._configuration_stopping = True

    async def drain_configuration_resources(self):
        self._configuration_stopping = True
        generations = {*self._retired_resources, self._runtime_snapshot.resources}
        await asyncio.gather(*(resources.drained.wait() for resources in generations))
        for resources in generations:
            if not resources.closed:
                resources.closed = True
                await self._close_resources(resources)
        if self._resource_cleanup_tasks:
            await asyncio.gather(*self._resource_cleanup_tasks, return_exceptions=True)


def _resource_property(name):
    def get(self):
        snapshot = self._snapshot()
        if snapshot is not None:
            return getattr(snapshot.resources, name)
        return getattr(self, "_initial_" + name)

    def set_(self, value):
        snapshot = self._snapshot()
        if snapshot is not None:
            setattr(snapshot.resources, name, value)
        else:
            setattr(self, "_initial_" + name, value)
    return property(get, set_)


for _attribute, _field in {
    "_mcp_tool_names": "mcp_names", "_mcp_dirty": "dirty", "_mcp_lock": "lock",
    "_mcp_startup_task": "startup_task",
}.items():
    setattr(RuntimeSnapshotMixin, _attribute, _resource_property(_field))


def _task_tools_property(field, initial):
    def get(self):
        binding = _TASK_TOOLS.get()
        if binding is not None and binding.owner is self:
            return getattr(binding, field)
        return getattr(self, initial)

    def set_(self, value):
        binding = _TASK_TOOLS.get()
        if binding is not None and binding.owner is self:
            setattr(binding, field, value)
        else:
            setattr(self, initial, value)
    return property(get, set_)


for _attribute, _field, _initial in (
    ("_skills_catalog_by_name", "skills", "_initial_skill_catalog"),
    ("_skill_tools_registered", "skill_tools_registered", "_initial_skill_registered"),
    ("_skill_registered_names", "skill_registered_names", "_initial_skill_names"),
):
    setattr(RuntimeSnapshotMixin, _attribute, _task_tools_property(_field, _initial))
