from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from quickquip.app.web.routes import stats, rules, groups

_DIST = Path(__file__).parent.parent.parent.parent / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="QuickQuip Admin")

    app.include_router(stats.router, prefix="/api")
    app.include_router(rules.router, prefix="/api")
    app.include_router(groups.router, prefix="/api")

    if _DIST.exists():
        app.mount("/ops", StaticFiles(directory=_DIST, html=True), name="static")

    return app
