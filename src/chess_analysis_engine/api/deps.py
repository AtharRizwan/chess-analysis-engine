from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from chess_analysis_engine.api.state import AppState


def get_state(request: Request) -> AppState:
    return request.app.state.app


StateDep = Annotated[AppState, Depends(get_state)]
