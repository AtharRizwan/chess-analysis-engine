"""Shared pieces for importing games from chess.com and lichess."""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass

import chess.pgn
import httpx

from chess_analysis_engine import __version__
from chess_analysis_engine.storage.db import Database

USER_AGENT = f"chess-analysis-engine/{__version__} (local learning tool)"


class ImportFailed(RuntimeError):
    pass


@dataclass
class ImportedGame:
    source: str
    source_id: str
    url: str | None
    pgn: str
    white: str
    black: str
    white_rating: int | None
    black_rating: int | None
    result: str
    time_class: str | None
    time_control: str | None
    played_at: str | None
    user_color: str | None


def make_client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


def pgn_result(pgn: str) -> str:
    headers = chess.pgn.read_headers(io.StringIO(pgn))
    return headers.get("Result", "*") if headers else "*"


def user_color_for(username: str, white: str, black: str) -> str | None:
    name = username.lower()
    if white.lower() == name:
        return "white"
    if black.lower() == name:
        return "black"
    return None


def save_games(db: Database, games: list[ImportedGame]) -> list[tuple[int, bool]]:
    """Store games, skipping ones already imported. Returns (game id, newly created) pairs."""
    return [db.upsert_game(asdict(g)) for g in games]
