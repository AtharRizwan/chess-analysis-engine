"""Drills (spaced repetition) and cross-game insights, built from stored reviews."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from chess_analysis_engine.api.app import create_app
from chess_analysis_engine.api.state import AppState
from chess_analysis_engine.learn.drills import INTERVAL_DAYS, accepted_moves, drills_from_review, schedule
from chess_analysis_engine.learn.insights import aggregate, index_rows, review_stats
from chess_analysis_engine.models import (
    EngineLine,
    Explanation,
    Fact,
    GameReview,
    MoveReview,
    PlayerInfo,
    Score,
    SideSummary,
)

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


def move(ply, color, san, uci, cls, loss, *, facts=(), alternatives=(), phase="opening"):
    return MoveReview(
        ply=ply, move_number=(ply + 1) // 2, color=color, san=san, uci=uci,
        fen_before=START if ply == 1 else AFTER_E4, fen_after=AFTER_E4,
        eval_before=Score(cp=0), eval_after=Score(cp=0), win_before=50, win_after=50,
        ep_before=0.5, ep_after=0.5 - loss, ep_loss=loss, accuracy=100 - 100 * loss,
        classification=cls, best=alternatives[0] if alternatives else None,
        alternatives=list(alternatives), phase=phase, facts=list(facts),
        explanation=Explanation(headline="x", hints=["Look for a fork."], focus="g8"),
    )  # fmt: skip


def line(uci, san, cp):
    return EngineLine(uci=[uci], san=[san], score=Score(cp=cp), depth=10)


def review() -> GameReview:
    fork = Fact(id="f1", kind="allows_tactic", motif="fork", importance=78)
    alts = [line("g8f6", "Nf6", -40), line("e7e5", "e5", -32), line("d7d5", "d5", 0)]
    moves = [
        move(1, "white", "e4", "e2e4", "book", 0.0),
        move(2, "black", "f6", "f7f6", "blunder", 0.3, facts=[fork], alternatives=alts),
    ]
    return GameReview(
        white=PlayerInfo(name="A"), black=PlayerInfo(name="B"), result="1-0", start_fen=START,
        user_color="black", preset="quick", depth=10, engine="test", moves=moves,
        summary={"white": SideSummary(accuracy=99.0), "black": SideSummary(accuracy=40.0)},
    )  # fmt: skip


def test_accepted_moves_are_the_lines_close_to_best():
    blunder = review().moves[1]
    # Black to move, best first: -32 centipawns (White's view) is within 0.02 expected points of -40; 0 isn't.
    assert accepted_moves(blunder) == ["g8f6", "e7e5"]


def test_drills_only_for_the_users_costly_moves():
    rows = drills_from_review(7, review())
    assert len(rows) == 1
    row = rows[0]
    assert row["ply"] == 2 and row["played"] == "f6" and row["best"] == "Nf6"
    assert '"fork"' in row["themes"] and row["moves"] == '["e2e4"]'
    assert drills_from_review(7, review().model_copy(update={"user_color": None})) == []


def test_leitner_schedule():
    now = datetime(2026, 10, 1, tzinfo=UTC)
    assert schedule(1, True, now) == (2, datetime(2026, 10, 4, tzinfo=UTC).isoformat())
    assert schedule(5, True, now)[0] == 5
    assert schedule(4, False, now) == (1, datetime(2026, 10, 1 + INTERVAL_DAYS[1], tzinfo=UTC).isoformat())


def test_insights_group_costly_moves_by_cause():
    r = review()
    rows = index_rows(7, r)
    assert [row["is_user"] for row in rows] == [0, 1]
    user_rows = [{**row, "white": "A", "black": "B", "played_at": None} for row in rows if row["is_user"]]
    stats = [{**review_stats(r, None), "game_id": 7, "result": "1-0"}]
    report = aggregate(user_rows, stats)
    assert report.games == 1 and report.accuracy == 40.0 and report.blunders_per_game == 1
    (cause,) = report.causes
    assert (cause.cause, cause.motif, cause.count) == ("allows_tactic", "fork", 1)
    assert cause.lesson and "Forks" in cause.lesson
    assert cause.examples[0].opponent == "A"


@pytest.fixture
def client(db):
    with TestClient(create_app(AppState(db=db))) as c:
        yield c


def test_drill_api_round_trip(client, db, fixtures):
    game_id = client.post("/api/import/pgn", json={"pgn": (fixtures / "opera_game.pgn").read_text()}).json()[
        "games"
    ][0]["id"]
    db.save_review(game_id, "quick", "done", review().model_dump_json())
    assert client.get("/api/drills/stats").json() == {"due": 1, "total": 1, "boxes": {"1": 1}}
    (card,) = client.get("/api/drills/due").json()
    assert card["hints"] == ["Look for a fork."] and card["focus"] == "g8" and card["color"] == "black"

    result = client.post(f"/api/drills/{card['id']}/attempt", json={"move": "g8f6"}).json()
    assert result["correct"] is True and result["solution"] == "Nf6" and result["card"]["box"] == 2
    assert client.get("/api/drills/stats").json()["due"] == 0
    assert client.post(f"/api/drills/{card['id']}/attempt", json={"move": "e1e2"}).status_code == 400

    insights = client.get("/api/insights").json()
    assert insights["games"] == 1 and insights["causes"][0]["motif"] == "fork"
