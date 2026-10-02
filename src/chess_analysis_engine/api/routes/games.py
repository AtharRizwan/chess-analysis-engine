"""Importing games (PGN, chess.com, lichess) and listing them."""

from __future__ import annotations

import chess.pgn
from fastapi import APIRouter, HTTPException

from chess_analysis_engine.api.deps import StateDep
from chess_analysis_engine.api.schemas import (
    GameSummary,
    ImportAccountRequest,
    ImportPgnRequest,
    ImportResult,
    UserColorRequest,
)
from chess_analysis_engine.api.state import AppState
from chess_analysis_engine.importers import chesscom, lichess
from chess_analysis_engine.importers.common import ImportedGame, ImportFailed, save_games
from chess_analysis_engine.pgn import GameRecord, PgnError, detect_user_color, read_games

router = APIRouter(prefix="/api", tags=["games"])


def _stored(state: AppState, games: list[ImportedGame]) -> ImportResult:
    saved = save_games(state.db, games)
    summaries = []
    for game_id, _ in saved:
        row = state.db.get_game(game_id)
        if row is not None:
            summaries.append(state.game_summary(row))
    return ImportResult(games=summaries, created=sum(1 for _, created in saved if created))


@router.post("/import/pgn", response_model=ImportResult)
def import_pgn(body: ImportPgnRequest, state: StateDep) -> ImportResult:
    try:
        records = read_games(body.pgn)
    except PgnError as exc:
        raise HTTPException(400, str(exc)) from exc
    usernames = state.settings().usernames()
    games = [
        ImportedGame(
            source="pgn",
            source_id=record.fingerprint(),
            url=_url(record.headers),
            pgn=body.pgn if len(records) == 1 else _single(record),
            white=record.white,
            black=record.black,
            white_rating=record.rating("white"),
            black_rating=record.rating("black"),
            result=record.result,
            time_class=None,
            time_control=record.headers.get("TimeControl"),
            played_at=_played_at(record.headers),
            user_color=body.user_color or detect_user_color(record, usernames),
        )
        for record in records
    ]
    return _stored(state, games)


def _url(headers: dict[str, str]) -> str | None:
    """chess.com puts the game link in [Link], lichess in [Site]."""
    for key in ("Link", "Site"):
        if headers.get(key, "").startswith("http"):
            return headers[key]
    return None


def _single(record: GameRecord) -> str:
    """Rebuild a one-game PGN from a parsed record (used when a file held several games)."""
    game = chess.pgn.Game()
    for key, value in record.headers.items():
        game.headers[key] = value
    if record.start_fen != game.board().fen():
        game.setup(record.start_fen)
    node = game
    for move, clock in zip(record.moves, record.clocks, strict=False):
        node = node.add_variation(move)
        if clock is not None:
            node.set_clock(clock)
    return str(game)


def _played_at(headers: dict[str, str]) -> str | None:
    date = headers.get("UTCDate") or headers.get("Date")
    if not date or "?" in date:
        return None
    time = headers.get("UTCTime", "00:00:00")
    return f"{date.replace('.', '-')}T{time}+00:00"


@router.post("/import/chesscom", response_model=ImportResult)
def import_chesscom(body: ImportAccountRequest, state: StateDep) -> ImportResult:
    try:
        games = chesscom.fetch_recent(body.username, body.max_games)
    except ImportFailed as exc:
        raise HTTPException(404, str(exc)) from exc
    settings = state.settings()
    if not settings.chesscom_username:
        state.save_settings(settings.model_copy(update={"chesscom_username": body.username.strip()}))
    return _stored(state, games)


@router.post("/import/lichess", response_model=ImportResult)
def import_lichess(body: ImportAccountRequest, state: StateDep) -> ImportResult:
    try:
        games = lichess.fetch_recent(body.username, body.max_games)
    except ImportFailed as exc:
        raise HTTPException(404, str(exc)) from exc
    settings = state.settings()
    if not settings.lichess_username:
        state.save_settings(settings.model_copy(update={"lichess_username": body.username.strip()}))
    return _stored(state, games)


@router.get("/games", response_model=list[GameSummary])
def list_games(state: StateDep) -> list[GameSummary]:
    return [state.game_summary(row) for row in state.db.list_games()]


@router.get("/games/{game_id}", response_model=GameSummary)
def get_game(game_id: int, state: StateDep) -> GameSummary:
    row = state.db.get_game(game_id)
    if row is None:
        raise HTTPException(404, "game not found")
    review = state.db.get_review(game_id)
    if review:
        row = {
            **row,
            "review_status": review["status"],
            "review_preset": review["preset"],
            "review_version": review["version"],
        }
    return state.game_summary(row)


@router.put("/games/{game_id}/side", response_model=GameSummary)
def set_side(game_id: int, body: UserColorRequest, state: StateDep) -> GameSummary:
    row = state.db.get_game(game_id)
    if row is None:
        raise HTTPException(404, "game not found")
    if row["user_color"] != body.user_color:
        state.db.forget_review(game_id)  # the review speaks to "you": redo it for the new side
    state.db.set_user_color(game_id, body.user_color)
    return get_game(game_id, state)
