from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from quickquip.app.web.routes import stats, rules, groups, config, memory, summaries

_DIST = Path(__file__).parent.parent.parent.parent / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="QuickQuip Admin")

    app.include_router(stats.router, prefix="/ops/api")
    app.include_router(rules.router, prefix="/ops/api")
    app.include_router(groups.router, prefix="/ops/api")
    app.include_router(config.router, prefix="/ops/api")
    app.include_router(memory.router, prefix="/ops/api")
    app.include_router(summaries.router, prefix="/ops/api")

    if _DIST.exists():
        app.mount("/ops", StaticFiles(directory=_DIST, html=True), name="static")

    return app
