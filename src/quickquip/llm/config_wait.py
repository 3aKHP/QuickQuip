"""Wait for a particular configuration task and its actual bot acknowledgement."""

import time

from quickquip.llm.config_errors import ConfigError


def wait_loaded(service, revision, *, operation=None, timeout=150, previous_boot=None):
    deadline = time.monotonic() + timeout
    while True:
        task = service.tasks.get(operation) if operation else {"status": "succeeded"}
        if task["status"] in ("failed", "cancelled"):
            raise ConfigError(
                "application_failed",
                "Configuration application failed",
                details={"operation": operation, "error": task.get("error")},
            )
        status = service.status()
        bot = status["bot"]
        if (
            task["status"] == "succeeded"
            and bot
            and not bot["stale"]
            and status["published_revision"] == revision
            and bot["loaded_revision"] == revision
            and bot["boot_id"] != previous_boot
            and bot["components"].get("core", {}).get("state") == "ready"
        ):
            return status
        if time.monotonic() >= deadline:
            raise ConfigError(
                "application_timeout",
                "Application remains unconfirmed",
                details={"operation": operation, "revision": revision},
            )
        time.sleep(1)
