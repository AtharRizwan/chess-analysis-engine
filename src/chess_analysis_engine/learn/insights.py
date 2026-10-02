"""Cross-game insights: what keeps costing you points, across every reviewed game."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from pydantic import BaseModel, Field

from chess_analysis_engine.explain.principles import lesson_for
from chess_analysis_engine.models import GameReview

BAD = {"inaccuracy", "mistake", "miss", "blunder"}
SERIOUS = {"mistake", "miss", "blunder"}
# Facts that can be "the reason" a move was costly, most specific first.
CAUSES = (
    "allows_mate",
    "missed_mate",
    "ignored_threat",
    "hangs_piece",
    "allows_tactic",
    "allows_attack",
    "loses_material",
    "missed_tactic",
    "missed_material",
    "missed_win",
    "tablebase",
    "stalemate",
    "positional",
    "opening_principle",
)
FAST_SECONDS = 5.0


class Example(BaseModel):
    game_id: int
    ply: int
    classification: str
    opponent: str | None = None


class Cause(BaseModel):
    cause: str
    motif: str | None = None
    count: int
    points_lost: float  # expected points lost in total (1.0 = a whole game)
    lesson: str | None = None
    examples: list[Example] = Field(default_factory=list)


class PhaseStat(BaseModel):
    phase: str
    moves: int
    accuracy: float | None


class TrendPoint(BaseModel):
    game_id: int
    played_at: str | None
    accuracy: float | None
    result: str | None = None


class Insights(BaseModel):
    games: int
    moves: int
    accuracy: float | None
    blunders_per_game: float | None
    mistakes_per_game: float | None
    fast_mistakes: int  # serious mistakes played in under FAST_SECONDS
    serious_with_clock: int  # serious mistakes where the clock time is known
    causes: list[Cause] = Field(default_factory=list)
    phases: list[PhaseStat] = Field(default_factory=list)
    trend: list[TrendPoint] = Field(default_factory=list)


def primary_cause(move: Any) -> tuple[str | None, str | None]:
    """The leading reason a move was costly, from its facts (already sorted by importance)."""
    for fact in move.facts:
        if fact.kind in CAUSES:
            motif = fact.motif or fact.data.get("pattern") or fact.data.get("how")
            return fact.kind, motif
    return None, None


def index_rows(game_id: int, review: GameReview) -> list[dict[str, Any]]:
    rows = []
    for move in review.moves:
        cause, motif = primary_cause(move) if move.classification in BAD else (None, None)
        rows.append(
            {
                "game_id": game_id,
                "ply": move.ply,
                "color": move.color,
                "is_user": int(move.color == review.user_color),
                "classification": move.classification,
                "ep_loss": move.ep_loss,
                "accuracy": move.accuracy,
                "phase": move.phase,
                "cause": cause or ("accuracy" if move.classification in BAD else None),
                "motif": motif,
                "spent": move.clock.spent if move.clock else None,
            }
        )
    return rows


def review_stats(review: GameReview, played_at: str | None) -> dict[str, Any]:
    side = review.user_color
    accuracy = review.summary[side].accuracy if side and side in review.summary else None
    return {"user_color": side, "accuracy": accuracy, "played_at": played_at}


def opponent_of(row: dict[str, Any]) -> str | None:
    return row["black"] if row["color"] == "white" else row["white"]


def aggregate(moves: list[dict[str, Any]], stats: list[dict[str, Any]], top: int = 6) -> Insights:
    games = len({m["game_id"] for m in moves})
    serious = [m for m in moves if m["classification"] in SERIOUS]
    grouped: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for move in moves:
        if move["classification"] in BAD and move["cause"]:
            grouped[(move["cause"], move["motif"])].append(move)
    causes = [
        Cause(
            cause=cause,
            motif=motif,
            count=len(items),
            points_lost=round(sum(m["ep_loss"] for m in items), 2),
            lesson=lesson_for(cause, motif),
            examples=[
                Example(
                    game_id=m["game_id"],
                    ply=m["ply"],
                    classification=m["classification"],
                    opponent=opponent_of(m),
                )
                for m in sorted(items, key=lambda m: -m["ep_loss"])[:5]
            ],
        )
        for (cause, motif), items in grouped.items()
    ]
    causes.sort(key=lambda c: -c.points_lost)
    phases = []
    for phase in ("opening", "middlegame", "endgame"):
        items = [m["accuracy"] for m in moves if m["phase"] == phase]
        phases.append(
            PhaseStat(phase=phase, moves=len(items), accuracy=round(mean(items), 1) if items else None)
        )
    accuracies = [s["accuracy"] for s in stats if s["accuracy"] is not None]
    timed = [m for m in serious if m["spent"] is not None]
    return Insights(
        games=games,
        moves=len(moves),
        accuracy=round(mean(accuracies), 1) if accuracies else None,
        blunders_per_game=round(sum(m["classification"] == "blunder" for m in moves) / games, 2)
        if games
        else None,
        mistakes_per_game=round(sum(m["classification"] in ("mistake", "miss") for m in moves) / games, 2)
        if games
        else None,
        fast_mistakes=sum(1 for m in timed if m["spent"] <= FAST_SECONDS),
        serious_with_clock=len(timed),
        causes=causes[:top],
        phases=phases,
        trend=[
            TrendPoint(
                game_id=s["game_id"], played_at=s["played_at"], accuracy=s["accuracy"], result=s["result"]
            )
            for s in stats
        ],
    )
