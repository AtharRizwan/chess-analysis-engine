import json

import httpx
import pytest

from chess_analysis_engine.importers import chesscom, lichess
from chess_analysis_engine.importers.common import ImportFailed, save_games

PGN = '[White "Alice"]\n[Black "Bob"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'


def chesscom_transport(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/pub/player/alice/games/archives":
        return httpx.Response(200, json={"archives": [
            "https://api.chess.com/pub/player/alice/games/2026/08",
            "https://api.chess.com/pub/player/alice/games/2026/09",
        ]})  # fmt: skip
    if path.endswith("/2026/09"):
        return httpx.Response(200, json={"games": [
            {"uuid": "g2", "url": "https://www.chess.com/game/live/2", "pgn": PGN, "rules": "chess",
             "end_time": 1790000000, "time_class": "rapid", "time_control": "600",
             "white": {"username": "Alice", "rating": 900}, "black": {"username": "Bob", "rating": 950}},
            {"uuid": "g3", "url": "https://www.chess.com/game/live/3", "pgn": PGN, "rules": "chess960",
             "end_time": 1790000100, "white": {"username": "Alice"}, "black": {"username": "Bob"}},
        ]})  # fmt: skip
    if path.endswith("/2026/08"):
        return httpx.Response(200, json={"games": [
            {"uuid": "g1", "url": "https://www.chess.com/game/live/1", "pgn": PGN, "rules": "chess",
             "end_time": 1780000000, "white": {"username": "Bob"}, "black": {"username": "Alice"}},
        ]})  # fmt: skip
    return httpx.Response(404)


def test_chesscom_newest_first_standard_only(db):
    client = httpx.Client(transport=httpx.MockTransport(chesscom_transport))
    games = chesscom.fetch_recent("Alice", max_games=5, client=client)
    assert [g.source_id for g in games] == ["g2", "g1"]
    assert games[0].user_color == "white" and games[1].user_color == "black"
    assert games[0].result == "1-0"
    assert games[0].played_at is not None and games[0].played_at.startswith("2026")

    first = save_games(db, games)
    again = save_games(db, games)
    assert all(created for _, created in first)
    assert not any(created for _, created in again)
    assert [gid for gid, _ in first] == [gid for gid, _ in again]


def test_chesscom_unknown_user():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(ImportFailed):
        chesscom.fetch_recent("nobody", client=client)


def test_lichess_ndjson_export():
    lines = [
        {"id": "abc", "variant": "standard", "pgn": PGN, "speed": "blitz", "createdAt": 1790000000000,
         "clock": {"initial": 180, "increment": 2},
         "players": {"white": {"user": {"name": "Alice"}, "rating": 1500}, "black": {"aiLevel": 3}}},
        {"id": "zzz", "variant": "chess960", "pgn": PGN, "players": {}},
    ]  # fmt: skip
    body = "\n".join(json.dumps(x) for x in lines) + "\n"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept"] == "application/x-ndjson"
        assert request.url.params["pgnInJson"] == "true"
        return httpx.Response(200, text=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    games = lichess.fetch_recent("alice", max_games=5, client=client)
    assert len(games) == 1
    game = games[0]
    assert game.source_id == "abc" and game.user_color == "white"
    assert game.black == "Stockfish level 3"
    assert game.time_control == "180+2"
