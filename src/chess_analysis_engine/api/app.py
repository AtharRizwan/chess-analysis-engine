"""The FastAPI application: JSON API under /api, plus the built web app (web/dist) at /."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from chess_analysis_engine import __version__
from chess_analysis_engine.api.routes import coach, explain, games, learn, reviews, settings
from chess_analysis_engine.api.state import AppState
from chess_analysis_engine.config import REPO_ROOT
from chess_analysis_engine.services import EngineNotFound, default_db, open_pool

WEB_DIST = REPO_ROOT / "web" / "dist"
INTERACTIVE_ENGINES = 2


def create_app(state: AppState | None = None) -> FastAPI:
    """Build the app. Tests pass their own state; `chess-analysis serve` lets it start engines."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = state is None
        app_state = state or _default_state()
        app.state.app = app_state
        yield
        if owned:
            for pool in (app_state.review_pool, app_state.interactive_pool):
                if pool is not None:
                    pool.close()

    app = FastAPI(title="Chess Analysis Engine", version=__version__, lifespan=lifespan)
    if state is not None:
        app.state.app = state
    for module in (games, reviews, explain, learn, coach, settings):
        app.include_router(module.router)
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app


def _default_state() -> AppState:
    db = default_db()
    try:
        review_pool = open_pool(db)
        interactive_pool = open_pool(db, size=INTERACTIVE_ENGINES)
    except EngineNotFound:
        review_pool = interactive_pool = None
    return AppState(db=db, review_pool=review_pool, interactive_pool=interactive_pool)
