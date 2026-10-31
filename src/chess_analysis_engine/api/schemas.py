"""Request and response models for the HTTP API (the web app's types are generated from these)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from chess_analysis_engine.models import Color, MoveReview, Score

PresetName = Literal["quick", "standard", "deep"]
# How the coach reaches Claude: your Anthropic API key, or your Claude plan through Claude Code.
CoachBackend = Literal["api", "claude_code"]


class Settings(BaseModel):
    chesscom_username: str = ""
    lichess_username: str = ""
    preset: PresetName = "standard"
    threats: bool = True  # null-move threat searches ("what did my opponent threaten?")
    tablebase: bool = True  # look up endgames with 7 pieces or fewer online (lichess)
    coach_enabled: bool = False  # optional Claude narration
    coach_backend: CoachBackend = "api"
    coach_model: str = "claude-opus-5-5"
    coach_effort: Literal["low", "medium", "high"] = "medium"

    def usernames(self) -> list[str]:
        return [u for u in (self.chesscom_username, self.lichess_username) if u.strip()]


class GameSummary(BaseModel):
    id: int
    source: str
    url: str | None = None
    white: str | None = None
    black: str | None = None
    white_rating: int | None = None
    black_rating: int | None = None
    result: str | None = None
    time_class: str | None = None
    time_control: str | None = None
    played_at: str | None = None
    user_color: Color | None = None
    review_status: str | None = None
    review_preset: str | None = None


class ImportPgnRequest(BaseModel):
    pgn: str
    user_color: Color | None = None


class ImportAccountRequest(BaseModel):
    username: str
    max_games: int = Field(default=20, ge=1, le=100)


class ImportResult(BaseModel):
    games: list[GameSummary]
    created: int


class ReviewRequest(BaseModel):
    preset: PresetName | None = None


class UserColorRequest(BaseModel):
    user_color: Color | None


class JobStatus(BaseModel):
    id: str
    game_id: int
    preset: str
    status: Literal["queued", "running", "done", "error"]
    stage: str = ""
    done: int = 0
    total: int = 0
    error: str | None = None


class ExplainRequest(BaseModel):
    """A move to explain: `moves` (UCI) lead from `fen` to the position where `move` is played."""

    fen: str
    moves: list[str] = Field(default_factory=list)
    move: str
    user_color: Color | None = None
    preset: PresetName | None = None


class EvaluateRequest(BaseModel):
    """A line to evaluate: `fen` and the position after each of `moves` (UCI)."""

    fen: str
    moves: list[str] = Field(default_factory=list, max_length=40)


class PositionScore(BaseModel):
    """One position's evaluation: the engine's score and White's winning chances in %."""

    score: Score
    win: float


class Health(BaseModel):
    version: str
    engine: str | None
    engines: int


class NarrateRequest(BaseModel):
    """A move to retell in the coach's voice (any reviewed or explored move)."""

    move: MoveReview
    user_color: Color | None = None
    refresh: bool = False  # ignore the cached narration and ask again


class CoachUsage(BaseModel):
    backend: CoachBackend
    model: str
    calls: int
    rejected: int  # replies that failed the grounding checks (each was retried or replaced)
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float | None  # estimate from API list prices; None on a Claude plan or for unpriced models


class CoachStatus(BaseModel):
    enabled: bool
    ready: bool  # turned on and usable right now
    backend: CoachBackend
    model: str
    effort: str
    problem: str | None = None  # why it can't be used: missing package, credentials or Claude Code
    usage: list[CoachUsage] = Field(default_factory=list)
