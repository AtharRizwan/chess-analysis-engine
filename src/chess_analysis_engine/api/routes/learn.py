"""The learning loop: drills from your own mistakes, and insights across your games."""

from __future__ import annotations

import json

import chess
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from chess_analysis_engine.api.deps import StateDep
from chess_analysis_engine.config import PRESETS
from chess_analysis_engine.learn.drills import (
    CLOSE_CLASSES,
    GOOD_CLASSES,
    SOLVE_TOLERANCE,
    AttemptResult,
    DrillCard,
    DrillStats,
    Verdict,
    card,
    grade,
    now_iso,
)
from chess_analysis_engine.learn.insights import Insights, aggregate
from chess_analysis_engine.models import MoveReview
from chess_analysis_engine.review.single import review_move

router = APIRouter(prefix="/api", tags=["learn"])


class AttemptRequest(BaseModel):
    move: str


@router.get("/insights", response_model=Insights)
def insights(state: StateDep) -> Insights:
    state.backfill()
    return aggregate(state.db.user_moves(), state.db.review_stats())


@router.get("/drills/stats", response_model=DrillStats)
def drill_stats(state: StateDep) -> DrillStats:
    state.backfill()
    return DrillStats.model_validate(state.db.drill_counts(now_iso()))


@router.get("/drills/due", response_model=list[DrillCard])
def due_drills(state: StateDep, theme: str | None = None, limit: int = 20) -> list[DrillCard]:
    state.backfill()
    return [card(row) for row in state.db.due_drills(now_iso(), limit, theme)]


@router.get("/drills/{drill_id}", response_model=DrillCard)
def get_drill(drill_id: int, state: StateDep) -> DrillCard:
    row = state.db.get_drill(drill_id)
    if row is None:
        raise HTTPException(404, "drill not found")
    return card(row)


@router.get("/games/{game_id}/drills", response_model=list[DrillCard])
def game_drills(game_id: int, state: StateDep) -> list[DrillCard]:
    state.backfill()
    return [card(row) for row in state.db.drills_for_game(game_id)]


@router.post("/drills/{drill_id}/attempt", response_model=AttemptResult)
def attempt(drill_id: int, body: AttemptRequest, state: StateDep) -> AttemptResult:
    row = state.db.get_drill(drill_id)
    if row is None:
        raise HTTPException(404, "drill not found")
    board = chess.Board(row["start_fen"])
    for uci in json.loads(row["moves"]):
        board.push_uci(uci)
    try:
        move = chess.Move.from_uci(body.move)
    except ValueError as exc:
        raise HTTPException(400, "invalid move") from exc
    if not board.is_legal(move):
        raise HTTPException(400, f"{body.move} is not a legal move here")
    accepted: list[str] = json.loads(row["accepted"])
    verdict: Verdict = "solved" if body.move in accepted else "wrong"
    tried: MoveReview | None = None
    if verdict == "wrong":
        if state.interactive_pool is None:
            raise HTTPException(503, "Stockfish is not available")
        settings = state.settings()
        tried = review_move(
            board,
            move,
            state.interactive_pool,
            PRESETS[settings.preset],
            user_color=row["color"],
            db=state.db,
            threats=settings.threats,
            tablebase=settings.tablebase,
        )
        if tried.classification in GOOD_CLASSES or tried.ep_loss <= SOLVE_TOLERANCE:
            verdict = "solved"
            accepted.append(body.move)  # another good solution: remember it
        elif tried.classification in CLOSE_CLASSES:
            verdict = "close"
    state.db.update_drill(
        drill_id,
        **grade(row, verdict),
        attempts=row["attempts"] + 1,
        solved=row["solved"] + int(verdict == "solved"),
        last_result={"solved": "solved", "close": "close", "wrong": "missed"}[verdict],
        accepted=json.dumps(accepted),
    )
    updated = state.db.get_drill(drill_id)
    assert updated is not None
    return AttemptResult(
        verdict=verdict,
        correct=verdict == "solved",
        solution=row["best"],
        attempt=tried,
        answer=MoveReview.model_validate_json(row["payload"]),
        card=card(updated),
    )


@router.post("/drills/{drill_id}/reveal", response_model=MoveReview)
def reveal(drill_id: int, state: StateDep) -> MoveReview:
    row = state.db.get_drill(drill_id)
    if row is None:
        raise HTTPException(404, "drill not found")
    state.db.update_drill(drill_id, **grade(row, "wrong"), last_result="revealed")
    return MoveReview.model_validate_json(row["payload"])
