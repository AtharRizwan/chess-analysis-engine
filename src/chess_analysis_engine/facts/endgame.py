"""Endgame tablebase lookups (lichess tablebase API, positions with 7 pieces or fewer).

A tablebase knows the exact result of an endgame. When a move turns a won endgame into a draw,
or a draw into a loss, that is the clearest possible explanation. Lookups are cached; when the
network is unavailable we simply skip them.
"""

from __future__ import annotations

import json

import chess
import httpx

from chess_analysis_engine.importers.common import USER_AGENT
from chess_analysis_engine.storage.db import Database

TABLEBASE_URL = "https://tablebase.lichess.org/standard"
MAX_PIECES = 7
# lichess categories, for the side to move. "Cursed" wins / "blessed" losses are draws under the
# 50-move rule; "maybe" results are tablebase rounding we treat as the real result.
_CATEGORY = {
    "win": "win",
    "maybe-win": "win",
    "cursed-win": "draw",
    "draw": "draw",
    "blessed-loss": "draw",
    "maybe-loss": "loss",
    "loss": "loss",
}
_FLIP = {"win": "loss", "draw": "draw", "loss": "win"}
RANK = {"loss": 0, "draw": 1, "win": 2}


def in_range(board: chess.Board) -> bool:
    return chess.popcount(board.occupied) <= MAX_PIECES and not board.castling_rights


def lookup(board: chess.Board, db: Database | None = None, client: httpx.Client | None = None) -> dict | None:
    """{"category": win|draw|loss for the side to move, "best": uci} or None if unavailable."""
    if not in_range(board):
        return None
    fen = board.fen()
    if db is not None and (cached := db.tablebase_get(fen)) is not None:
        return json.loads(cached)
    try:
        http = client or httpx.Client(timeout=5.0, headers={"User-Agent": USER_AGENT})
        try:
            response = http.get(TABLEBASE_URL, params={"fen": fen})
        finally:
            if client is None:
                http.close()
        if response.status_code != 200:
            return None
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    category = _CATEGORY.get(data.get("category", ""))
    if category is None:
        return None
    moves = data.get("moves") or []
    result = {"category": category, "best": moves[0]["uci"] if moves else None}
    if db is not None:
        db.tablebase_put(fen, json.dumps(result))
    return result


def result_change(
    before: chess.Board, after: chess.Board, db: Database | None = None, client: httpx.Client | None = None
) -> tuple[str, str] | None:
    """(result before, result after) from the mover's side, when the move made it worse."""
    if not in_range(before) or not in_range(after) or after.is_game_over():
        return None
    was = lookup(before, db, client)
    now = lookup(after, db, client)
    if was is None or now is None:
        return None
    before_result = was["category"]
    after_result = _FLIP[now["category"]]  # `after` has the opponent to move
    if RANK[after_result] < RANK[before_result]:
        return before_result, after_result
    return None
