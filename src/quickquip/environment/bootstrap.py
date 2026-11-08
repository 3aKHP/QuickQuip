"""Entrypoint wiring for native and container environment consumers."""
from quickquip.common import runtime_environment
from quickquip.environment.transport import call


def start(role):
    import os
    from quickquip.common.env import PROJECT_ROOT
    # Existing private Compose installations opt in by adopting the agent template.
    # They retain their startup environment until the socket is configured.
    if not os.environ.get('QUICKQUIP_ENV_SOCKET') and not (PROJECT_ROOT / '.env').exists():
        return
    from quickquip.common.env import load_root_env_file
    load_root_env_file()
    import time
    from quickquip.environment.store import EnvironmentError

    deadline = time.monotonic() + 30
    while True:
        try:
            runtime_environment.start(
                lambda: call('snapshot'), lambda body: call('ack', body), role
            )
            return
        except (OSError, EnvironmentError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
