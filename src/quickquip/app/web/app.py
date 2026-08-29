from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from quickquip.app.web import auth
from quickquip.app.web.routes import stats, rules, groups, config, logs, diagnostics, memory, summaries, period_reports, personas, conversations, group_settings, rate_limit, tieba, wordcloud, llm_about, mcp_dashboard, cron_dashboard, audit, game_economy, niuniu, quotes, sensitive_filter, awakening, llm_runtime, llm_usage
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


def create_app() -> FastAPI:
    load_web_env()
    # web 进程独立运行，不经过 bot 的 startup；显式加载一次贴吧帖子池快照
    from quickquip.app.message_pipeline import tieba_service

    tieba_service.load()

    app = FastAPI(title="QuickQuip Admin")

    app.include_router(auth.router, prefix="/ops/api")
    app.include_router(stats.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(rules.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(groups.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(config.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(logs.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(diagnostics.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(memory.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(summaries.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(period_reports.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(personas.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(conversations.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(group_settings.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(rate_limit.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(tieba.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(wordcloud.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(llm_about.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(mcp_dashboard.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(cron_dashboard.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(audit.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(game_economy.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(niuniu.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(quotes.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(sensitive_filter.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(awakening.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(llm_runtime.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(llm_usage.router, prefix="/ops/api", dependencies=auth.protected_dependencies)

    _register_root_redirect(app)

    if _DIST.exists():
        app.mount(_OPS_PREFIX, StaticFiles(directory=_DIST, html=True), name="static")

    return app
