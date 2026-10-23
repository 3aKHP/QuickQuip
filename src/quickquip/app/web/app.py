from fastapi import FastAPI
from fastapi.responses import RedirectResponse, JSONResponse
from quickquip.common.config_writes import ConfigurationBusy
from fastapi.staticfiles import StaticFiles
from quickquip.app.web import auth
from quickquip.app.web.routes import (
    stats,
    rules,
    groups,
    config,
    logs,
    diagnostics,
    memory,
    summaries,
    period_reports,
    personas,
    conversations,
    group_settings,
    rate_limit,
    tieba,
    wordcloud,
    llm_about,
    mcp_dashboard,
    cron_dashboard,
    audit,
    game_economy,
    niuniu,
    quotes,
    sensitive_filter,
    awakening,
    llm_runtime,
    llm_usage,
    llm_effort,
    epochs,
    scheduled_messages,
    skills,
    llm_configuration,
)
from quickquip.app.web.settings import load_web_env
from quickquip.common.env import PROJECT_ROOT

_DIST = PROJECT_ROOT / "frontend" / "dist"
_OPS_PREFIX = "/ops"


def _register_root_redirect(app: FastAPI) -> None:
    # 管理台挂在 _OPS_PREFIX 下，直接访问根路径此前得到 404（v1.12.2 验收发现）；
    # 重定向到控制台入口，无斜杠前缀由 Starlette mount 自动 307 补全。
    @app.get("/", include_in_schema=False)
    async def _root() -> RedirectResponse:
        return RedirectResponse(f"{_OPS_PREFIX}/")


# 全站安全响应头：CSP 允许同源 + data:/https: 图片（词云 base64、贴吧 imgproxy、
# 总结外链图）与内联样式（组件 style 绑定）；SSE 走同源 connect-src。
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def _register_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def _security_headers(request, call_next):
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


def create_app() -> FastAPI:
    load_web_env()
    from quickquip.llm.client_fingerprints.catalog import get_catalog

    get_catalog()
    # web 进程独立运行，不经过 bot 的 startup；显式加载一次贴吧帖子池快照
    from quickquip.app.message_pipeline import tieba_service

    tieba_service.load()

    # 管理 API 的 OpenAPI/文档端点不对网络暴露；llm-configuration 的公开机器契约
    # 由 scripts/ci/export_llm_configuration_openapi.py 在进程内导出维护。
    app = FastAPI(title="QuickQuip Admin", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ConfigurationBusy)
    async def configuration_busy_handler(request, error):
        return JSONResponse(status_code=409, content={
            "code": "configuration_busy", "message": str(error),
        })

    _register_security_headers(app)

    app.include_router(auth.router, prefix="/ops/api")
    app.include_router(stats.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(rules.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(groups.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(config.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(logs.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(
        diagnostics.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(memory.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(
        summaries.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(
        period_reports.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(personas.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(
        conversations.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(
        group_settings.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(
        rate_limit.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(tieba.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(
        wordcloud.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(
        llm_about.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(
        mcp_dashboard.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(
        cron_dashboard.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(audit.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(
        game_economy.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(niuniu.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(quotes.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(
        sensitive_filter.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(
        awakening.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(
        llm_runtime.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(
        llm_usage.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(
        llm_effort.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(
        epochs.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(
        scheduled_messages.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )
    app.include_router(skills.router, prefix="/ops/api", dependencies=auth.protected_dependencies)

    app.include_router(
        llm_configuration.router, prefix="/ops/api", dependencies=auth.protected_dependencies
    )

    _register_root_redirect(app)

    if _DIST.exists():
        app.mount(_OPS_PREFIX, StaticFiles(directory=_DIST, html=True), name="static")

    return app
