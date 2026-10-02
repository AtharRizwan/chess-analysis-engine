"""lichess game export importer: https://lichess.org/api#tag/Games/operation/apiGamesUser

lichess allows one request at a time per client; on HTTP 429 the rule is to wait a full
minute. An optional personal token ($CAE_LICHESS_TOKEN) raises the download speed.
"""

from __future__ import annotations

import json
import os
import threading
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

EXPORT_URL = "https://lichess.org/api/games/user/{username}"
RATE_LIMIT_WAIT = 60.0
_one_at_a_time = threading.Lock()


def _player(raw: dict[str, Any], color: str) -> tuple[str, int | None]:
    player = raw.get("players", {}).get(color, {})
    if "user" in player:
        return player["user"].get("name", color.title()), player.get("rating")
    if "aiLevel" in player:
        return f"Stockfish level {player['aiLevel']}", None
    return "Anonymous", None


def _to_game(raw: dict[str, Any], username: str) -> ImportedGame:
    white, white_rating = _player(raw, "white")
    black, black_rating = _player(raw, "black")
    clock = raw.get("clock") or {}
    created = raw.get("createdAt")
    return ImportedGame(
        source="lichess",
        source_id=raw["id"],
        url=f"https://lichess.org/{raw['id']}",
        pgn=raw["pgn"],
        white=white,
        black=black,
        white_rating=white_rating,
        black_rating=black_rating,
        result=pgn_result(raw["pgn"]),
        time_class=raw.get("speed"),
        time_control=f"{clock['initial']}+{clock['increment']}" if clock else None,
        played_at=datetime.fromtimestamp(created / 1000, UTC).isoformat(timespec="seconds")
        if created
        else None,
        user_color=user_color_for(username, white, black),
    )


def fetch_raw(
    username: str,
    max_games: int = 20,
    client: httpx.Client | None = None,
    token: str | None = None,
    include_evals: bool = False,
) -> list[dict[str, Any]]:
    """Raw lichess JSON for the most recent standard games of `username`, newest first.

    With `include_evals`, games analyzed on lichess carry lichess's own evaluations and
    judgments (useful to cross-check our classification).
    """
    username = username.strip()
    if not username:
        raise ImportFailed("Enter a lichess username.")
    params = {
        "max": str(max_games * 2),  # variants are filtered out below
        "pgnInJson": "true",
        "clocks": "true",
        "opening": "true",
        "evals": "true" if include_evals else "false",
    }
    headers = {"Accept": "application/x-ndjson"}
    token = token or os.environ.get("CAE_LICHESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    http = client or make_client(timeout=120.0)
    games: list[dict[str, Any]] = []
    try:
        with _one_at_a_time:
            for attempt in range(2):
                with http.stream(
                    "GET", EXPORT_URL.format(username=username), params=params, headers=headers
                ) as r:
                    if r.status_code == 429 and attempt == 0:
                        time.sleep(RATE_LIMIT_WAIT)
                        continue
                    if r.status_code == 404:
                        raise ImportFailed("lichess user not found (check the username).")
                    if r.status_code == 429:
                        raise ImportFailed("lichess is rate-limiting requests; try again in a minute.")
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line.strip():
                            continue
                        game = json.loads(line)
                        if game.get("variant") == "standard" and game.get("pgn"):
                            games.append(game)
                        if len(games) >= max_games:
                            break
                break
    finally:
        if client is None:
            http.close()
    return games


def fetch_recent(
    username: str,
    max_games: int = 20,
    client: httpx.Client | None = None,
    token: str | None = None,
) -> list[ImportedGame]:
    """Most recent standard games of `username`, newest first."""
    return [_to_game(g, username.strip()) for g in fetch_raw(username, max_games, client, token)]
