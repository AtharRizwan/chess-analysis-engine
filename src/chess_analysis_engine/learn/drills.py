"""Drills: your own mistakes, replayed with spaced repetition (Leitner boxes).

Each serious mistake you made becomes a card: the position before it, "find a better move".
Solve it and the card comes back later and later (1, 3, 7, 14, 30 days); miss it and it starts
over tomorrow.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from chess_analysis_engine.engine.scoring import ep_for
from chess_analysis_engine.models import Color, GameReview, MoveReview

INTERVAL_DAYS = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30}
MAX_BOX = 5
DRILL_CLASSES = {"mistake", "miss", "blunder"}
# Any move this close to the engine's best (expected points) counts as a solution.
SOLVE_TOLERANCE = 0.02
GOOD_CLASSES = {"best", "excellent", "great", "brilliant", "book", "forced"}


class DrillCard(BaseModel):
    id: int
    game_id: int
    ply: int
    start_fen: str
    moves: list[str]  # UCI moves from start_fen to the drill position
    fen: str
    color: Color
    played: str
    themes: list[str] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    focus: str | None = None
    box: int
    attempts: int
    due_at: str


class DrillStats(BaseModel):
    due: int
    total: int
    boxes: dict[str, int] = Field(default_factory=dict)


class AttemptResult(BaseModel):
    correct: bool
    solution: str  # the engine's move, SAN
    attempt: MoveReview | None = None  # your move, explained (when it wasn't the stored answer)
    answer: MoveReview  # the original mistake, fully explained
    card: DrillCard


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).isoformat(timespec="seconds")


def accepted_moves(move: MoveReview) -> list[str]:
    """Moves that solve the position: the engine's lines within SOLVE_TOLERANCE of the best."""
    lines = [line for line in move.alternatives if line.uci]
    if not lines:
        return [move.best.uci[0]] if move.best and move.best.uci else []
    best = ep_for(lines[0].score, move.color)
    return [
        line.uci[0]
        for line in lines
        if best - ep_for(line.score, move.color) <= SOLVE_TOLERANCE and line.uci[0] != move.uci
    ]


def themes_of(move: MoveReview) -> list[str]:
    tags: list[str] = []
    for fact in move.facts[:4]:
        for tag in (fact.kind, fact.motif):
            if tag and tag not in tags:
                tags.append(tag)
    return tags


def drills_from_review(game_id: int, review: GameReview, now: datetime | None = None) -> list[dict[str, Any]]:
    """New drill rows for the user's costly moves in a finished review."""
    if review.user_color is None:
        return []
    created = now_iso(now)
    rows = []
    for move in review.moves:
        if move.color != review.user_color or move.classification not in DRILL_CLASSES:
            continue
        accepted = accepted_moves(move)
        if not accepted or not move.best:
            continue
        rows.append(
            {
                "game_id": game_id,
                "ply": move.ply,
                "start_fen": review.start_fen,
                "moves": json.dumps([m.uci for m in review.moves[: move.ply - 1]]),
                "fen": move.fen_before,
                "color": move.color,
                "played": move.san,
                "best": move.best.san[0],
                "accepted": json.dumps(accepted),
                "themes": json.dumps(themes_of(move)),
                "payload": move.model_dump_json(),
                "box": 1,
                "due_at": created,
                "created_at": created,
            }
        )
    return rows


def schedule(box: int, correct: bool, now: datetime | None = None) -> tuple[int, str]:
    """Next Leitner box and due date after an attempt."""
    new_box = min(MAX_BOX, box + 1) if correct else 1
    due = (now or datetime.now(UTC)) + timedelta(days=INTERVAL_DAYS[new_box])
    return new_box, now_iso(due)


def card(row: dict[str, Any]) -> DrillCard:
    move = MoveReview.model_validate_json(row["payload"])
    explanation = move.explanation
    return DrillCard(
        id=row["id"],
        game_id=row["game_id"],
        ply=row["ply"],
        start_fen=row["start_fen"],
        moves=json.loads(row["moves"]),
        fen=row["fen"],
        color=row["color"],
        played=row["played"],
        themes=json.loads(row["themes"]),
        hints=explanation.hints if explanation else [],
        focus=explanation.focus if explanation else None,
        box=row["box"],
        attempts=row["attempts"],
        due_at=row["due_at"],
    )
