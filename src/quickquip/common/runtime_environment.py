"""Process-local immutable environment views, pinned for one logical LLM task."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
import threading
import time
import uuid

_values = None
_version = None
_lease = ContextVar('credential_environment', default=None)
_lock = threading.Lock()


def install(values, version):
    global _values, _version
    with _lock:
        _values, _version = dict(values), version


def managed():
    return _values is not None


def snapshot():
    leased = _lease.get()
    if leased is not None:
        return leased
    with _lock:
        return dict(os.environ) if _values is None else dict(_values)


def get(name, default=None):
    return snapshot().get(name, default)


@contextmanager
def credential_scope():
    if not managed():
        yield
        return
    token = _lease.set(snapshot())
    try:
        yield
    finally:
        _lease.reset(token)


def install_snapshot(result, baseline):
    """Overlay explicit managed values and tombstones on the legacy environment."""
    values = dict(baseline)
    for name in result['managed']:
        value = result['values'].get(name)
        if value is not None:
            values[name] = value
    for name in result['deleted']:
        values.pop(name, None)
    install(values, result['version'])
    return values


def start(loader, acknowledge, role):
    boot_id = uuid.uuid4().hex
    startup_values = dict(os.environ)
    first_ack = True
    def update():
        nonlocal first_ack
        result = loader()
        values = install_snapshot(result, startup_values)
        # Tieba's existing reload_config reads these two variables at task boundaries.
        for name in ('TIEBA_FORUM_KEYWORD', 'TIEBA_FORUM_KEYWORDS'):
            if name in values:
                os.environ[name] = values[name]
            else:
                os.environ.pop(name, None)
        body = {'role': role, 'version': result['version'], 'boot_id': boot_id,
                'updated_at': time.time(), 'names': sorted(values)}
        if first_ack:
            body['startup_values'] = startup_values
        acknowledge(body)
        first_ack = False
    update()  # Bootstrap must not fall back to stale Docker-injected credentials.
    def poll():
        while True:
            time.sleep(5)
            try:
                update()
            except (OSError, ValueError):
                # Keep the last confirmed snapshot and let the expired ack show the outage.
                pass
    threading.Thread(target=poll, name='environment-refresh', daemon=True).start()
