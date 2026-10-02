"""The "why not this move?" explorer: explain any move from any position."""

from __future__ import annotations

import chess
from fastapi import APIRouter, HTTPException

from chess_analysis_engine.api.deps import StateDep
from chess_analysis_engine.api.schemas import ExplainRequest
from chess_analysis_engine.config import PRESETS
from chess_analysis_engine.models import MoveReview
from chess_analysis_engine.review.single import review_move

router = APIRouter(prefix="/api", tags=["explain"])


@router.post("/explain", response_model=MoveReview)
def explain(body: ExplainRequest, state: StateDep) -> MoveReview:
    if state.interactive_pool is None:
        raise HTTPException(503, "Stockfish is not available")
    try:
        board = chess.Board(body.fen)
        for uci in body.moves:
            board.push_uci(uci)
        move = chess.Move.from_uci(body.move)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid position or move: {exc}") from exc
    if not board.is_legal(move):
        raise HTTPException(400, f"{body.move} is not a legal move here")
    settings = state.settings()
    preset = PRESETS[body.preset or settings.preset]
    return review_move(
        board,
        move,
        state.interactive_pool,
        preset,
        user_color=body.user_color,
        db=state.db,
        threats=settings.threats,
        tablebase=settings.tablebase,
    )
