#!/usr/bin/env python3
"""QuickQuip Admin API entrypoint with a configuration lifetime lease."""

from quickquip.common.env import PROJECT_ROOT
from quickquip.configuration.activity import service_guard
from quickquip.configuration.process_supervisor import managed_entrypoint


def main():
    with service_guard(PROJECT_ROOT, "web"):
        import uvicorn
        from quickquip.configuration.migration import require_fresh_layout
        from quickquip.app.web.app import create_app
        from quickquip.app.web.settings import get_web_admin_host, get_web_admin_port

        require_fresh_layout(PROJECT_ROOT)
        from quickquip.environment.bootstrap import start as start_environment

        start_environment("web")
        uvicorn.run(create_app(), host=get_web_admin_host(), port=get_web_admin_port())


if __name__ == "__main__":
    raise SystemExit(managed_entrypoint(PROJECT_ROOT, "web", main))
