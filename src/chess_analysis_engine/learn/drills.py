"""Drills: your own mistakes, replayed with spaced repetition (Leitner boxes).

Each serious mistake you made becomes a card: the position before it, "find a better move".
Solve it and the card comes back later and later (1, 3, 7, 14, 30 days); miss it and it starts
over tomorrow.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from chess_analysis_engine.engine.scoring import ep_for
from chess_analysis_engine.explain.phrases import move_label, numbered_line
from chess_analysis_engine.models import Classification, Color, GameReview, LineRef, MoveReview

INTERVAL_DAYS = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30}
MAX_BOX = 5
DRILL_CLASSES = {"mistake", "miss", "blunder"}
# Any move this close to the engine's best (expected points) counts as a solution.
SOLVE_TOLERANCE = 0.02
GOOD_CLASSES = {"best", "excellent", "great", "brilliant", "book", "forced"}
# A try that's good but not the answer: no miss, but keep looking.
CLOSE_CLASSES = {"good"}

Verdict = Literal["solved", "close", "wrong"]


class DrillCard(BaseModel):
    id: int
    game_id: int
    ply: int
    start_fen: str
    moves: list[str]  # UCI moves from start_fen to the drill position
    fen: str
    color: Color
    played: str
    played_uci: str = ""
    classification: Classification = "mistake"
    win_before: float = 50.0  # White's winning chances (%) before and after the move you played
    win_after: float = 50.0
    why: str = ""  # why the played move is bad, without giving away the better move
    why_line: LineRef | None = None  # the played move and what follows it
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
    verdict: Verdict
    correct: bool  # verdict == "solved"
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


def grade(row: dict[str, Any], verdict: Verdict, now: datetime | None = None) -> dict[str, Any]:
    """Schedule changes after a try (or a reveal, graded as "wrong").

    Only a card that is due gets graded, once: the first wrong try (or a reveal) sends it back to box 1,
    a solve moves it up a box. Tries on a card that isn't due (after a miss in the same session, or
    practice from a game) and "close" tries change nothing.
    """
    if verdict == "close" or row["due_at"] > now_iso(now):
        return {}
    box, due = schedule(row["box"], verdict == "solved", now)
    return {"box": box, "due_at": due}


def _mentions(text: str, san: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(san.rstrip('+#'))}(?![a-z0-9])", text) is not None


def _from_drill_position(move: MoveReview, line: LineRef | None) -> LineRef | None:
    """A line after the played move, starting one move earlier so it shows the played move first."""
    if line is None or not line.uci:
        return None
    if line.start_fen == move.fen_after:
        return LineRef(start_fen=move.fen_before, uci=[move.uci, *line.uci], san=[move.san, *line.san])
    return line


def why_bad(move: MoveReview) -> tuple[str, LineRef | None]:
    """Why the played move is bad, for the drill's intro: never names the better move to play now."""
    explanation = move.explanation
    wrong = (
        next((s for s in explanation.sections if s.title == "What went wrong"), None) if explanation else None
    )
    refutation = (
        LineRef(start_fen=move.fen_after, uci=move.refutation.uci[:8], san=move.refutation.san[:8])
        if move.refutation and move.refutation.uci
        else None
    )
    best = move.best.san[0] if move.best and move.best.san else None
    if wrong:
        text, line = wrong.text, wrong.line or refutation
    else:
        # Misses and engine-only moves: their explanation is about the better move, so describe the result.
        headline = explanation.headline.strip() if explanation else ""
        if headline and not (best and _mentions(headline, best)):
            text = f"It {headline[0].lower()}{headline[1:].rstrip('.')}."
        else:
            text = "There was a clearly stronger move here."
        line = refutation
    if refutation and not re.search(r"\d\.", text):
        # No moves in the reason yet (e.g. "It gives up the bishop pair."): say what happens next.
        played = move_label(move.move_number, move.color, move.san)
        text += f" After {played}, best play continues {numbered_line(move.fen_after, refutation.san, 4)}."
    return text, _from_drill_position(move, line)


def card(row: dict[str, Any]) -> DrillCard:
    move = MoveReview.model_validate_json(row["payload"])
    explanation = move.explanation
    why, why_line = why_bad(move)
    return DrillCard(
        id=row["id"],
        game_id=row["game_id"],
        ply=row["ply"],
        start_fen=row["start_fen"],
        moves=json.loads(row["moves"]),
        fen=row["fen"],
        color=row["color"],
        played=row["played"],
        played_uci=move.uci,
        classification=move.classification,
        win_before=move.win_before,
        win_after=move.win_after,
        why=why,
        why_line=why_line,
        themes=json.loads(row["themes"]),
        hints=explanation.hints if explanation else [],
        focus=explanation.focus if explanation else None,
        box=row["box"],
        attempts=row["attempts"],
        due_at=row["due_at"],
    )
