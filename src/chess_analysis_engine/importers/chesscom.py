"""chess.com PubAPI importer (public data, no auth): https://www.chess.com/news/view/published-data-api

Requests are made one at a time; parallel requests get rate-limited (HTTP 429).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx

from chess_analysis_engine.importers.common import (
    ImportedGame,
    ImportFailed,
    make_client,
    pgn_result,
    user_color_for,
)

ARCHIVES_URL = "https://api.chess.com/pub/player/{username}/games/archives"


def _get(http: httpx.Client, url: str) -> Any:
    delay = 2.0
    for _ in range(4):
        response = http.get(url)
        if response.status_code == 429:
            time.sleep(delay)
            delay *= 2
            continue
        if response.status_code == 404:
            raise ImportFailed("chess.com user not found (check the username).")
        response.raise_for_status()
        return response.json()
    raise ImportFailed("chess.com is rate-limiting requests; try again in a minute.")


def _to_game(raw: dict[str, Any], username: str) -> ImportedGame:
    white, black = raw.get("white", {}), raw.get("black", {})
    end = raw.get("end_time")
    return ImportedGame(
        source="chesscom",
        source_id=raw.get("uuid") or raw["url"],
        url=raw.get("url"),
        pgn=raw["pgn"],
        white=white.get("username", "White"),
        black=black.get("username", "Black"),
        white_rating=white.get("rating"),
        black_rating=black.get("rating"),
        result=pgn_result(raw["pgn"]),
        time_class=raw.get("time_class"),
        time_control=raw.get("time_control"),
        played_at=datetime.fromtimestamp(end, UTC).isoformat(timespec="seconds") if end else None,
        user_color=user_color_for(username, white.get("username", ""), black.get("username", "")),
    )


def fetch_recent(
    username: str, max_games: int = 20, client: httpx.Client | None = None
) -> list[ImportedGame]:
    """Most recent standard-chess games of `username`, newest first."""
    username = username.strip()
    if not username:
        raise ImportFailed("Enter a chess.com username.")
    http = client or make_client()
    try:
        archives: list[str] = _get(http, ARCHIVES_URL.format(username=username.lower())).get("archives", [])
        games: list[ImportedGame] = []
        for url in reversed(archives):
            month = _get(http, url).get("games", [])
            for raw in sorted(month, key=lambda g: g.get("end_time", 0), reverse=True):
                if raw.get("rules") != "chess" or not raw.get("pgn"):
                    continue
                games.append(_to_game(raw, username))
                if len(games) >= max_games:
                    return games
        return games
    finally:
        if client is None:
            http.close()
