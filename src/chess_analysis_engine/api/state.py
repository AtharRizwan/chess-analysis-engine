"""Shared application state: database, engine pools, review jobs and settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chess_analysis_engine.api.jobs import Job, JobManager
from chess_analysis_engine.api.schemas import GameSummary, Settings
from chess_analysis_engine.config import PRESETS
from chess_analysis_engine.engine.pool import EnginePool
from chess_analysis_engine.explain.coach_llm import make_client
from chess_analysis_engine.learn.drills import drills_from_review
from chess_analysis_engine.learn.insights import index_rows, review_stats
from chess_analysis_engine.models import REVIEW_VERSION, GameReview
from chess_analysis_engine.pgn import detect_user_color, read_games
from chess_analysis_engine.review.pipeline import ReviewOptions, review_game
from chess_analysis_engine.storage.db import Database

SETTINGS_KEY = "app"


@dataclass
class AppState:
    db: Database
    review_pool: EnginePool | None = None  # many single-threaded engines for whole-game reviews
    interactive_pool: EnginePool | None = None  # a couple of engines for "why not?" questions
    coach_client: Any = None  # Anthropic client for the optional coach, created on first use
    jobs: JobManager = field(init=False)

    def __post_init__(self) -> None:
        self.jobs = JobManager(self.run_review)

    @property
    def engine_name(self) -> str | None:
        pool = self.review_pool or self.interactive_pool
        return pool.name if pool else None

    def settings(self) -> Settings:
        return Settings.model_validate(self.db.get_setting(SETTINGS_KEY, {}))

    def save_settings(self, settings: Settings) -> Settings:
        self.db.set_setting(SETTINGS_KEY, settings.model_dump())
        return settings

    def coach(self) -> Any:
        """The Anthropic client; raises CoachError when the package or credentials are missing."""
        if self.coach_client is None:
            self.coach_client = make_client()
        return self.coach_client

    def game_summary(self, row: dict) -> GameSummary:
        fields = {k: v for k, v in row.items() if k in GameSummary.model_fields}
        if fields.get("review_status") == "done" and (row.get("review_version") or 1) < REVIEW_VERSION:
            fields["review_status"] = "outdated"  # reviewed by an older version: the app redoes it
        return GameSummary.model_validate(fields)

    def run_review(self, job: Job) -> None:
        if self.review_pool is None:
            raise RuntimeError("Stockfish is not available")
        row = self.db.get_game(job.game_id)
        if row is None:
            raise RuntimeError("game not found")
        settings = self.settings()
        (game,) = read_games(row["pgn"])[:1]
        user_color = row["user_color"] or detect_user_color(game, settings.usernames())
        if user_color and not row["user_color"]:
            self.db.set_user_color(job.game_id, user_color)
        self.db.save_review(job.game_id, job.preset, "running")
        try:
            options = ReviewOptions(
                preset=PRESETS[job.preset],
                user_color=user_color,
                threats=settings.threats,
                tablebase=settings.tablebase,
            )
            review = review_game(game, self.review_pool, options, progress=job.progress, db=self.db)
        except Exception as exc:
            self.db.save_review(job.game_id, job.preset, "error", error=str(exc))
            raise
        self.db.save_review(job.game_id, job.preset, "done", review.model_dump_json(), version=review.version)
        self.learn_from(job.game_id, review, row["played_at"])

    def learn_from(self, game_id: int, review: GameReview, played_at: str | None) -> None:
        """Index a finished review for insights and turn your mistakes into drills."""
        self.db.index_review(game_id, review_stats(review, played_at), index_rows(game_id, review))
        drills = drills_from_review(game_id, review)
        for drill in drills:
            self.db.add_drill(drill)
        self.db.prune_drills(game_id, [d["ply"] for d in drills])

    def backfill(self) -> None:
        """Index reviews that finished before the learning tables existed (or were redone)."""
        for row in self.db.unindexed_reviews():
            self.learn_from(row["game_id"], GameReview.model_validate_json(row["payload"]), row["played_at"])
