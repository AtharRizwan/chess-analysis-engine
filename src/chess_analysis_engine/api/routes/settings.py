from __future__ import annotations

from fastapi import APIRouter

from chess_analysis_engine import __version__
from chess_analysis_engine.api.deps import StateDep
from chess_analysis_engine.api.schemas import Health, Settings

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/health", response_model=Health)
def health(state: StateDep) -> Health:
    engines = state.review_pool.size if state.review_pool else 0
    return Health(version=__version__, engine=state.engine_name, engines=engines)


@router.get("/settings", response_model=Settings)
def get_settings(state: StateDep) -> Settings:
    return state.settings()


@router.put("/settings", response_model=Settings)
def put_settings(body: Settings, state: StateDep) -> Settings:
    return state.save_settings(body)
