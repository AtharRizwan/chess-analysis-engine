"""The "why not this move?" explorer: explain any move from any position, and evaluate the
positions along a line as you step through it."""

from __future__ import annotations

import chess
from fastapi import APIRouter, HTTPException

from chess_analysis_engine.api.deps import StateDep
from chess_analysis_engine.api.schemas import EvaluateRequest, ExplainRequest, PositionScore
from chess_analysis_engine.config import PRESETS
from chess_analysis_engine.engine.pool import Request
from chess_analysis_engine.engine.scoring import white_win_percent
from chess_analysis_engine.models import MoveReview
from chess_analysis_engine.review.single import review_move

router = APIRouter(prefix="/api", tags=["explain"])

# Stepping through a line should feel instant: a quick search per position is plenty for the bar.
LINE_PRESET = PRESETS["quick"]


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


@router.post("/evaluate", response_model=list[PositionScore])
def evaluate(body: EvaluateRequest, state: StateDep) -> list[PositionScore]:
    """Evaluate `fen` and the position after each move of the line, in order."""
    if state.interactive_pool is None:
        raise HTTPException(503, "Stockfish is not available")
    try:
        board = chess.Board(body.fen)
        boards = [board.copy()]
        for uci in body.moves:
            board.push_uci(uci)
            boards.append(board.copy())  # keeps the moves, so repetitions in the line count
    except ValueError as exc:
        raise HTTPException(400, f"Invalid position or move: {exc}") from exc
    # Last position first, so the engine's hash carries the end of the line back to its start.
    requests = [
        Request(b, depth=LINE_PRESET.depth, max_seconds=LINE_PRESET.max_seconds) for b in reversed(boards)
    ]
    evals = reversed(state.interactive_pool.analyse_many(requests))
    return [PositionScore(score=e.score, win=round(white_win_percent(e.score), 2)) for e in evals]
