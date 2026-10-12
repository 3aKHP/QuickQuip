"""Bot-owned consumer of immutable configuration control operations."""
from __future__ import annotations

import asyncio
import errno
from dataclasses import asdict, replace
from importlib.metadata import PackageNotFoundError, version
import logging
import os
import time
import uuid

from quickquip.llm.config_document import (
    compile_document, environment_references, resolve_model_provider,
)
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.provider_health import probe_provider
from quickquip.llm.usage import configuration_pricing

logger = logging.getLogger(__name__)


def initialize_for_bot(service, legacy_path=None, *, wait_seconds=20, sleep=time.sleep):
    """A read-only bot waits for a writable Web/CLI initializer to prepare assets."""
    try:
        service.initialize(legacy_path)
    except OSError as exc:
        if not isinstance(exc, PermissionError) and exc.errno != errno.EROFS:
            raise
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if service.path.exists():
                return service.read("published")
            sleep(min(0.25, max(0, deadline - time.monotonic())))
        raise ConfigError(
            "migration_required",
            "Writable Web/CLI initialization must prepare configuration assets",
        ) from None
    return service.read("published")


class ConfigRuntimeWorker:
    """Prepare outside transactions, fence publication, then confirm actual load."""

    def __init__(self, service, runtime, *, compiler=compile_document, schedules=None):
        self.service = service
        self.runtime = runtime
        self.compiler = compiler
        self.schedules = schedules
        self.boot_id = uuid.uuid4().hex
        self._tick_lock = asyncio.Lock()
        try:
            self.application_version = version("quickquip")
        except PackageNotFoundError:
            self.application_version = "unknown"
        initial_config = runtime.config
        self.boot_id = service.register_bot_boot(
            self.boot_id, initial_config.revision, application_version=self.application_version
        )
        runtime._configuration_boot_check = lambda: service.assert_bot_boot(self.boot_id)
        # Once registration fences older boots, the published pointer stays stable until
        # this worker begins consuming operations. A startup paused before registration
        # must refresh the pointer rather than accepting new work with an older snapshot.
        published = service.read("published")
        if published["revision"] != runtime.config.revision:
            current = runtime.config
            config = self.compiler(
                published["document"], revision=published["revision"],
                config_dir=runtime.config_path.parent.parent / "config",
            )
            snapshot = runtime.prepare_configuration(config)
            if schedules is not None:
                with runtime.configuration_view(snapshot):
                    schedules(current, config)
            runtime.activate_configuration(snapshot)
            if snapshot.resources.dirty:
                with runtime.configuration_view(snapshot):
                    runtime.start_mcp_background()

    def components(self):
        runtime = self.runtime
        statuses = runtime.mcp_manager.get_statuses()
        required = set(environment_references(self.service.read("published")["document"]))
        required.update(environment_references(self.service.read("draft")["document"]))
        return {
            "environment": [{"name": name, "configured": bool(os.getenv(name))}
                            for name in sorted(required)],
            "core": {"state": "ready" if not runtime.config.load_error else "failed"},
            "mcp": {
                "state": "preparing" if (
                    runtime.is_mcp_initializing() or runtime.is_mcp_dirty()
                ) else (
                    "degraded" if any(s.enabled and not s.connected for s in statuses) else "ready"
                ),
                "servers": [{"id": s.id, "connected": s.connected,
                             "failure_code": s.failure_kind} for s in statuses],
            },
        }

    def report(self):
        try:
            self.service.report_bot(
                self.boot_id, self.runtime.config.revision, self.components(),
                application_version=self.application_version,
            )
        except ConfigError as exc:
            if exc.code == "runtime_superseded":
                self.runtime.fence_configuration_runtime()
            raise

    def _verify(self, operation):
        self.service.assert_bot_boot(self.boot_id)
        with self.service.store.connect() as conn:
            self.service.tasks.assert_claim(conn, operation["id"], operation["claim_token"])

    def _validate_local(self, config, document):
        if config.load_error:
            raise ConfigError("configuration_failed", "Configuration could not be compiled")
        required_providers = set()
        required_models = set()
        def model(provider_id, selected, location):
            try:
                effective = resolve_model_provider(config, provider_id, selected)
                required_providers.add(provider_id)
                required_models.add((provider_id, effective.aliases.get(selected, selected)))
                return effective
            except ConfigError as exc:
                raise ConfigError(exc.code, exc.message, location, exc.details) from None

        default_id = config.runtime.default_provider or ""
        default_provider = config.providers.get(default_id)
        default_model = default_provider.default_model if default_provider else ""
        if config.runtime.enabled:
            model(default_id, default_model, "settings.runtime.default_provider")
        reports = ("daily_summary", "daily_briefing", "weekly_report", "monthly_report")
        if config.runtime.enabled or any(getattr(config, name).enabled for name in reports):
            if config.runtime.default_persona not in config.personas:
                raise ConfigError("missing_persona", "Default persona file is missing",
                                  "settings.runtime.default_persona")
        for name in reports:
            report = getattr(config, name)
            if not report.enabled:
                continue
            for index, entry in enumerate(report.model_cascade or ["@default"]):
                provider_id, selected = (
                    (default_id, default_model) if entry == "@default" else entry.split("/", 1)
                )
                model(provider_id, selected, f"routes.{name}[{index}]")
        judge = config.quick_judge
        if judge.provider_id or judge.model:
            provider_id = judge.provider_id or default_id
            provider = config.providers.get(provider_id)
            selected = judge.model or (provider.default_model if provider else "")
            model(provider_id, selected, "settings.quick_judge")
        image = config.image_preprocessing
        if image.enabled:
            provider_id = image.provider_id
            provider = config.providers.get(provider_id)
            selected = image.model or (provider.default_model if provider else "")
            effective = model(provider_id, selected, "settings.image_preprocessing")
            wire = effective.aliases.get(selected, selected)
            if wire in effective.non_vision_models:
                raise ConfigError("vision_required", "Image preprocessing requires a vision model",
                                  "settings.image_preprocessing.model")
        active_providers = [{
            **provider,
            "models": [m for m in provider["models"]
                       if (provider["id"], m["model"]) in required_models],
        } for provider in document["providers"] if provider["id"] in required_providers]
        missing = [name for name in environment_references({"providers": active_providers})
                   if not os.getenv(name)]
        if missing:
            raise ConfigError("missing_environment", "Required environment variables missing",
                              details={"variables": sorted(set(missing))})

    def _validate_overrides(self, document):
        store = self.runtime.store
        if store is None:
            return
        self.service.validate_group_overrides(document, store)

    async def _renew(self, operation):
        while True:
            await asyncio.sleep(5)
            self.service.assert_bot_boot(self.boot_id)
            self.service.tasks.heartbeat(operation["id"], operation["claim_token"])
            self.report()

    async def _probe(self, operation, config):
        payload = operation["payload"]
        provider = resolve_model_provider(config, payload["provider_id"], payload["model"])
        with configuration_pricing(config):
            if "user_prompt" in payload:
                from quickquip.llm.provider import (
                    LLMRequest, RetryPolicy, build_provider_client,
                )
                from quickquip.llm.tools import LLMConversationMessage
                client = build_provider_client(
                    replace(
                        provider, fallback_urls=[], stream_enabled=payload.get("stream", False)
                    ),
                    retry_policy=RetryPolicy.disabled(), single_dispatch=True,
                )
                request = LLMRequest(
                    model=payload["model"], system_prompt=payload.get("system_prompt", ""),
                    messages=[LLMConversationMessage(role="user", content=payload["user_prompt"])],
                    max_output_tokens=payload.get("max_output_tokens", 64),
                    temperature=0.0, tools=[], allow_tool_calls=False,
                )
                response = await asyncio.wait_for(client.complete(request), timeout=30)
                return {"revision": config.revision, "may_be_billable": True,
                        "automatic_retries": False, "text": response.text[:8192],
                        "model": response.model, "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "finish_reason": response.finish_reason}
            result = await probe_provider(provider, model=payload["model"])
        return {"probe": asdict(result), "revision": operation["target_revision"],
                "may_be_billable": True, "automatic_retries": False}

    async def _apply(self, operation, config, document):
        self._verify(operation)
        self._validate_local(config, document)
        snapshot = self.runtime.prepare_configuration(config)
        old_config = self.runtime.config
        rollback = None
        try:
            self.service.tasks.update_stage(operation["id"], operation["claim_token"], "switching")
            async with self.runtime._configuration_gate:
                # Shared reference lock excludes concurrent group overrides across processes.
                if self.schedules is not None:
                    with self.runtime.configuration_view(snapshot):
                        rollback = self.schedules(old_config, config)
                self.service.publish(
                    operation["id"], operation["claim_token"],
                    before_publish=lambda: self._validate_overrides(document),
                    boot_id=self.boot_id,
                )
                self._verify(operation)
                self.runtime.activate_configuration(snapshot)
                self._verify(operation)
            with self.runtime.configuration_view(snapshot):
                if snapshot.resources.dirty:
                    self.runtime.start_mcp_background()
            self.report()
        except BaseException as exc:
            if isinstance(exc, ConfigError) and exc.code == "runtime_superseded":
                self.runtime.fence_configuration_runtime()
            if rollback is not None and snapshot is not self.runtime._runtime_snapshot:
                rollback()
            if snapshot is not self.runtime._runtime_snapshot:
                if snapshot.resources is not self.runtime._runtime_snapshot.resources:
                    await self.runtime._close_resources(snapshot.resources)
            raise
        return {"loaded_revision": config.revision, "components": self.components()}

    async def tick(self):
        """Called every five seconds by the bot adapter; Web never executes this."""
        if self._tick_lock.locked():
            return
        async with self._tick_lock:
            self.report()
            operation = self.service.tasks.claim(self.boot_id, boot_id=self.boot_id)
            if operation is None:
                return
            heartbeat = asyncio.create_task(self._renew(operation))
            try:
                target = self.service.read(operation["target_revision"])
                self._verify(operation)
                config = self.compiler(
                    target["document"], revision=target["revision"],
                    config_dir=self.runtime.config_path.parent.parent / "config",
                )
                execution = asyncio.create_task(
                    self._apply(operation, config, target["document"])
                    if operation["kind"] == "apply"
                    else self._probe(operation, config)
                )
                done, _ = await asyncio.wait(
                    {execution, heartbeat}, return_when=asyncio.FIRST_COMPLETED
                )
                if heartbeat in done:
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                    heartbeat.result()
                result = await execution
                self._verify(operation)
                self.service.tasks.finish(operation["id"], operation["claim_token"], result=result)
            except asyncio.CancelledError:
                # Leave the fenced lease for restart recovery; probes are never replayed.
                if "execution" in locals():
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                raise
            except Exception as exc:
                if isinstance(exc, ConfigError) and exc.code == "runtime_superseded":
                    self.runtime.fence_configuration_runtime()
                    return
                error = exc.as_dict() if isinstance(exc, ConfigError) else {
                    "code": "configuration_failed", "message": "Configuration operation failed",
                    "field_path": "", "details": {"exception_type": type(exc).__name__},
                }
                try:
                    self.service.tasks.finish(operation["id"], operation["claim_token"],
                                              status="failed", error=error)
                except ConfigError:
                    logger.warning("Configuration operation ownership expired")
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
