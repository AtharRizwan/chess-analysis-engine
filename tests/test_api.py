"""HTTP API tests. Engine-backed flows are marked `engine`."""

import time

import pytest
from fastapi.testclient import TestClient

from chess_analysis_engine.api.app import create_app
from chess_analysis_engine.api.state import AppState
from chess_analysis_engine.models import REVIEW_VERSION


@pytest.fixture
def client(db):
    with TestClient(create_app(AppState(db=db))) as c:
        yield c


@pytest.fixture
def engine_client(db, pool):
    with TestClient(create_app(AppState(db=db, review_pool=pool, interactive_pool=pool))) as c:
        yield c


def test_health_and_settings(client):
    assert client.get("/api/health").json()["engine"] is None
    settings = client.get("/api/settings").json()
    assert settings["preset"] == "standard" and settings["learn_mode"] is True
    settings["chesscom_username"] = "AtharxRizwan"
    assert client.put("/api/settings", json=settings).json()["chesscom_username"] == "AtharxRizwan"
    assert client.get("/api/settings").json()["chesscom_username"] == "AtharxRizwan"


def test_import_pgn_list_and_pick_side(client, fixtures):
    pgn = (fixtures / "opera_game.pgn").read_text()
    result = client.post("/api/import/pgn", json={"pgn": pgn}).json()
    assert result["created"] == 1
    game = result["games"][0]
    assert game["white"] == "Paul Morphy" and game["user_color"] is None
    again = client.post("/api/import/pgn", json={"pgn": pgn}).json()
    assert again["created"] == 0 and again["games"][0]["id"] == game["id"]

    assert [g["id"] for g in client.get("/api/games").json()] == [game["id"]]
    updated = client.put(f"/api/games/{game['id']}/side", json={"user_color": "white"}).json()
    assert updated["user_color"] == "white"


def test_multi_game_pgn_is_split(client, fixtures):
    result = client.post(
        "/api/import/pgn", json={"pgn": (fixtures / "beginner_traps.pgn").read_text()}
    ).json()
    assert result["created"] == 2
    assert {g["black"] for g in result["games"]} == {"Trapper", "Learner"}


def test_errors_without_engine(client, fixtures):
    assert client.post("/api/import/pgn", json={"pgn": "not a pgn"}).status_code == 400
    game_id = client.post("/api/import/pgn", json={"pgn": (fixtures / "opera_game.pgn").read_text()}).json()[
        "games"
    ][0]["id"]
    assert client.post(f"/api/games/{game_id}/review", json={}).status_code == 503
    assert client.get(f"/api/games/{game_id}/review").status_code == 404
    assert (
        client.post("/api/explain", json={"fen": "8/8/8/8/8/8/8/8 w - - 0 1", "move": "e2e4"}).status_code
        == 503
    )


@pytest.mark.engine
def test_review_flow_and_why_not(engine_client, fixtures):
    pgn = (fixtures / "beginner_traps.pgn").read_text().split("\n\n[Event")[0]
    game_id = engine_client.post("/api/import/pgn", json={"pgn": pgn, "user_color": "white"}).json()["games"][
        0
    ]["id"]
    job = engine_client.post(f"/api/games/{game_id}/review", json={"preset": "quick"}).json()
    assert job["status"] in ("queued", "running")
    deadline = time.time() + 120
    while engine_client.get(f"/api/jobs/{job['id']}").json()["status"] not in ("done", "error"):
        assert time.time() < deadline
        time.sleep(0.2)
    assert engine_client.get(f"/api/jobs/{job['id']}").json()["status"] == "done"

    events = engine_client.get(f"/api/jobs/{job['id']}/events").text
    assert '"status":"done"' in events

    review = engine_client.get(f"/api/games/{game_id}/review").json()
    assert len(review["moves"]) == 14 and review["user_color"] == "white"
    assert engine_client.get("/api/games").json()[0]["review_status"] == "done"

    # Why not 4. Nxd4 instead of 4. Nxe5? Explain both from the same position.
    start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    history = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "c6d4"]
    good = engine_client.post(
        "/api/explain",
        json={"fen": start, "moves": history, "move": "f3d4", "user_color": "white", "preset": "quick"},
    ).json()
    bad = engine_client.post(
        "/api/explain",
        json={"fen": start, "moves": history, "move": "f3e5", "user_color": "white", "preset": "quick"},
    ).json()
    assert good["classification"] in ("best", "excellent", "great")
    assert bad["classification"] in ("mistake", "blunder", "inaccuracy")
    assert any(f["kind"] == "allows_attack" for f in bad["facts"])
    assert (
        engine_client.post("/api/explain", json={"fen": start, "moves": history, "move": "e1e3"}).status_code
        == 400
    )


def test_outdated_reviews_are_redone(client, db, fixtures):
    game_id = client.post("/api/import/pgn", json={"pgn": (fixtures / "opera_game.pgn").read_text()}).json()[
        "games"
    ][0]["id"]
    db.save_review(game_id, "quick", "done", "{}", version=1)
    assert client.get(f"/api/games/{game_id}").json()["review_status"] == "outdated"
    db.save_review(game_id, "quick", "done", "{}", version=REVIEW_VERSION)
    assert client.get(f"/api/games/{game_id}").json()["review_status"] == "done"
    assert client.get("/api/games").json()[0]["review_status"] == "done"


def test_changing_side_discards_the_review(client, db, fixtures):
    game_id = client.post("/api/import/pgn", json={"pgn": (fixtures / "opera_game.pgn").read_text()}).json()[
        "games"
    ][0]["id"]
    db.save_review(game_id, "quick", "done", "{}", version=REVIEW_VERSION)
    client.put(f"/api/games/{game_id}/side", json={"user_color": "black"})
    assert db.get_review(game_id) is None


@pytest.mark.engine
def test_drill_wrong_attempt_is_explained(engine_client, fixtures):
    pgn = (fixtures / "beginner_traps.pgn").read_text().split("\n\n[Event")[0]
    game_id = engine_client.post("/api/import/pgn", json={"pgn": pgn, "user_color": "white"}).json()["games"][
        0
    ]["id"]
    job = engine_client.post(f"/api/games/{game_id}/review", json={"preset": "quick"}).json()
    deadline = time.time() + 120
    while engine_client.get(f"/api/jobs/{job['id']}").json()["status"] not in ("done", "error"):
        assert time.time() < deadline
        time.sleep(0.2)
    cards = engine_client.get("/api/drills/due").json()
    blunder = next(c for c in cards if c["played"] == "Nxf7")
    assert blunder["hints"], "drills carry retry hints"
    # Playing the game's blunder again is wrong, and the answer says why.
    result = engine_client.post(f"/api/drills/{blunder['id']}/attempt", json={"move": "e5f7"}).json()
    assert result["correct"] is False
    assert result["attempt"]["classification"] in ("mistake", "blunder")
    assert result["card"]["box"] == 1 and result["answer"]["san"] == "Nxf7"
