"""Entrypoint wiring for explicitly enabled environment consumers."""
import time

from quickquip.common import runtime_environment
from quickquip.common.env import environment_management_enabled
from quickquip.environment.store import EnvironmentError
from quickquip.environment.transport import call


def start(role):
    if not environment_management_enabled():
        return
    deadline = time.monotonic() + 30
    while True:
        try:
            call('initialize')
            runtime_environment.start(
                lambda: call('snapshot'), lambda body: call('ack', body), role
            )
            return
        except (OSError, EnvironmentError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
