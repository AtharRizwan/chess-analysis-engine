"""Data models shared by the analysis core, the API and the CLI.

Evaluations (`Score`) are always stored from White's point of view; helpers in
`engine.scoring` convert them to the mover's perspective.
"""

from __future__ import annotations

from typing import Any, Literal

import chess
from pydantic import BaseModel, Field

# Bump when a review's content changes in a way the app relies on; older stored reviews are redone.
# 2: explanations carry retry hints.
# 3: Brilliant needs a sacrifice the move itself makes; Great excludes obvious only-moves.
# 4: labels on a curve fitted to chess.com; losing a forced mate is a Miss; Great = punishing an error.
REVIEW_VERSION = 4

Color = Literal["white", "black"]
Phase = Literal["opening", "middlegame", "endgame"]
Difficulty = Literal["easy", "medium", "hard"]
Classification = Literal[
    "brilliant",
    "great",
    "best",
    "excellent",
    "good",
    "book",
    "forced",
    "inaccuracy",
    "mistake",
    "miss",
    "blunder",
]
CLASSIFICATIONS: tuple[Classification, ...] = (
    "brilliant",
    "great",
    "best",
    "excellent",
    "good",
    "book",
    "forced",
    "inaccuracy",
    "mistake",
    "miss",
    "blunder",
)


def color_name(color: chess.Color) -> Color:
    return "white" if color == chess.WHITE else "black"


def color_of(name: Color) -> chess.Color:
    return chess.WHITE if name == "white" else chess.BLACK


def other(color: Color) -> Color:
    return "black" if color == "white" else "white"


class Score(BaseModel):
    """An evaluation from White's point of view.

    Exactly one of `cp`, `mate` or `result` is set. `mate` counts moves (positive: White
    mates); `result` marks a finished game (checkmate, stalemate, insufficient material).
    """

    cp: int | None = None
    mate: int | None = None
    result: Literal["1-0", "0-1", "1/2-1/2"] | None = None

    def display(self) -> str:
        if self.result is not None:
            return {"1-0": "1-0", "0-1": "0-1"}.get(self.result, "½-½")
        if self.mate is not None:
            return f"#{self.mate}" if self.mate > 0 else f"#-{-self.mate}"
        cp = self.cp or 0
        return f"{cp / 100:+.2f}"


class EngineLine(BaseModel):
    """A principal variation from some position, in UCI and SAN."""

    uci: list[str]
    san: list[str]
    score: Score
    depth: int


class PositionEval(BaseModel):
    """Engine analysis of one position. `lines` is best-first (MultiPV)."""

    fen: str
    score: Score
    lines: list[EngineLine] = Field(default_factory=list)
    depth: int = 0
    engine: str = ""
    # (depth, best move) as the search deepened; used to judge how hard a move is to find.
    best_by_depth: list[tuple[int, str]] = Field(default_factory=list)

    @property
    def best(self) -> EngineLine | None:
        return self.lines[0] if self.lines else None


class LineRef(BaseModel):
    """A sequence of moves from a given position, ready to be replayed in the UI."""

    start_fen: str
    uci: list[str]
    san: list[str]


class Annotation(BaseModel):
    """Something to draw on the board: an arrow (orig→dest) or a circle (orig)."""

    orig: str
    dest: str | None = None
    brush: Literal["green", "red", "blue", "yellow", "grey"] = "green"


class Fact(BaseModel):
    """A verified statement about a move, produced by an analyzer in `facts/`.

    `kind` says what happened (e.g. "allows_tactic", "ignored_threat"), `motif` names the
    pattern (e.g. "fork", "back_rank_mate"). `actor` is the side carrying out the idea.
    `material` is the material (centipawns) the actor nets along `line`.
    """

    id: str
    kind: str
    motif: str | None = None
    actor: Color | None = None
    importance: float = 0.0
    squares: list[str] = Field(default_factory=list)
    line: LineRef | None = None
    material: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    annotations: list[Annotation] = Field(default_factory=list)


class ExplanationSection(BaseModel):
    title: str
    text: str
    fact_ids: list[str] = Field(default_factory=list)
    line: LineRef | None = None


class Explanation(BaseModel):
    headline: str
    sections: list[ExplanationSection] = Field(default_factory=list)
    lesson: str | None = None
    annotations: list[Annotation] = Field(default_factory=list)
    source: Literal["template", "coach"] = "template"
    # For retrying a mistake: nudges that point the way without giving the move away, and the
    # square of the piece the better move uses (the second hint circles it).
    hints: list[str] = Field(default_factory=list)
    focus: str | None = None


class OpeningRef(BaseModel):
    eco: str
    name: str


class ClockInfo(BaseModel):
    remaining: float | None = None  # seconds left after the move
    spent: float | None = None  # seconds spent thinking on the move


class PlayerInfo(BaseModel):
    name: str
    rating: int | None = None


class MoveReview(BaseModel):
    ply: int  # 1-based index of the move in the game
    move_number: int
    color: Color
    san: str
    uci: str
    fen_before: str
    fen_after: str
    eval_before: Score
    eval_after: Score
    win_before: float  # White's winning chances in % (lichess curve, capped like lichess)
    win_after: float
    ep_before: float  # expected points for the mover with best play
    ep_after: float  # expected points for the mover after the played move
    ep_loss: float
    accuracy: float
    classification: Classification
    best: EngineLine | None = None  # mover's best line from fen_before
    refutation: EngineLine | None = None  # opponent's best line from fen_after
    alternatives: list[EngineLine] = Field(default_factory=list)
    phase: Phase = "opening"
    book: bool = False
    opening: OpeningRef | None = None
    clock: ClockInfo | None = None
    critical: bool = False  # re-analyzed with a deeper search
    sacrifice: int = 0  # material offered by the move (centipawns, static exchange view)
    key_moment: bool = False
    difficulty: Difficulty | None = None
    facts: list[Fact] = Field(default_factory=list)
    explanation: Explanation | None = None


class SideSummary(BaseModel):
    accuracy: float | None = None
    counts: dict[str, int] = Field(default_factory=dict)


class GameReview(BaseModel):
    version: int = REVIEW_VERSION
    headers: dict[str, str] = Field(default_factory=dict)
    white: PlayerInfo
    black: PlayerInfo
    result: str
    start_fen: str
    user_color: Color | None = None
    opening: OpeningRef | None = None
    left_book_ply: int | None = None
    preset: str
    depth: int
    engine: str
    moves: list[MoveReview] = Field(default_factory=list)
    final_eval: Score | None = None
    summary: dict[str, SideSummary] = Field(default_factory=dict)
    key_moments: list[int] = Field(default_factory=list)
    created_at: str = ""
