from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from quickquip.app.web import auth
from quickquip.app.web.routes import stats, rules, groups, config, diagnostics, memory, summaries, personas, conversations, group_settings, rate_limit, tieba, wordcloud, llm_about, mcp_dashboard, cron_dashboard, audit, game_economy, niuniu
from quickquip.app.web.settings import load_web_env

_DIST_V1 = Path(__file__).parent.parent.parent.parent / "frontend-v1" / "dist"
_DIST = Path(__file__).parent.parent.parent.parent / "frontend" / "dist"


def create_app() -> FastAPI:
    load_web_env()
    app = FastAPI(title="QuickQuip Admin")

    app.include_router(auth.router, prefix="/ops/api")
    app.include_router(stats.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(rules.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(groups.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(config.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(diagnostics.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(memory.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
    app.include_router(summaries.router, prefix="/ops/api", dependencies=auth.protected_dependencies)
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

    if _DIST_V1.exists():
        app.mount("/ops/v1", StaticFiles(directory=_DIST_V1, html=True), name="static-v1")
    if _DIST.exists():
        app.mount("/ops", StaticFiles(directory=_DIST, html=True), name="static")

    return app
