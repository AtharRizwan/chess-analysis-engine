"""Drills (spaced repetition) and cross-game insights, built from stored reviews."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from chess_analysis_engine.api.app import create_app
from chess_analysis_engine.api.state import AppState
from chess_analysis_engine.learn.drills import (
    INTERVAL_DAYS,
    accepted_moves,
    drills_from_review,
    grade,
    schedule,
    why_bad,
)
from chess_analysis_engine.learn.insights import aggregate, index_rows, review_stats
from chess_analysis_engine.models import (
    EngineLine,
    Explanation,
    ExplanationSection,
    Fact,
    GameReview,
    LineRef,
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


def test_why_bad_explains_the_played_move_without_the_answer():
    after_f6 = "rnbqkbnr/ppppp1pp/5p2/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    punish = LineRef(start_fen=after_f6, uci=["d1h5"], san=["Qh5+"])
    blunder = (
        review()
        .moves[1]
        .model_copy(
            update={
                "fen_after": after_f6,
                "refutation": EngineLine(uci=["d1h5"], san=["Qh5+"], score=Score(cp=300), depth=10),
                "explanation": Explanation(
                    headline="Weakens your king",
                    sections=[
                        ExplanationSection(
                            title="What went wrong", text="It opens the e8-h5 diagonal.", line=punish
                        ),
                        ExplanationSection(title="Better was 1...Nf6", text="It develops."),
                    ],
                ),
            }
        )
    )
    text, line = why_bad(blunder)
    # A reason without moves gets the continuation, so you can see how it goes wrong.
    assert text == "It opens the e8-h5 diagonal. After 1...f6, best play continues 2. Qh5+."
    # The line starts from the drill position, with the move you played first.
    assert line.start_fen == blunder.fen_before and line.san == ["f6", "Qh5+"]

    # A miss: its explanation is all about the better move, so describe what happened instead.
    miss = blunder.model_copy(deep=True)
    miss.explanation.headline = "Misses a fork"
    miss.explanation.sections = miss.explanation.sections[1:]
    text, line = why_bad(miss)
    assert text == "It misses a fork. After 1...f6, best play continues 2. Qh5+."
    assert "Nf6" not in text and line.san == ["f6", "Qh5+"]


def test_only_due_cards_are_graded():
    now = datetime(2026, 10, 2, 12, tzinfo=UTC)
    due = {"box": 2, "due_at": "2026-10-02T00:00:00+00:00"}
    assert grade(due, "solved", now) == {"box": 3, "due_at": "2026-10-09T12:00:00+00:00"}
    assert grade(due, "wrong", now) == {"box": 1, "due_at": "2026-10-03T12:00:00+00:00"}
    assert grade(due, "close", now) == {}
    # After a miss the card is due tomorrow, so solving it now (or practising early) changes nothing.
    missed = {**due, **grade(due, "wrong", now)}
    assert grade(missed, "solved", now) == {} and grade(missed, "wrong", now) == {}


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
    assert card["played_uci"] == "f7f6" and card["classification"] == "blunder" and card["why"]

    assert client.get(f"/api/drills/{card['id']}").json()["played"] == "f6"
    assert [c["ply"] for c in client.get(f"/api/games/{game_id}/drills").json()] == [2]
    assert client.get("/api/drills/999").status_code == 404

    result = client.post(f"/api/drills/{card['id']}/attempt", json={"move": "g8f6"}).json()
    assert result["verdict"] == "solved" and result["correct"] is True
    assert result["solution"] == "Nf6" and result["card"]["box"] == 2
    # Not due any more: another solve doesn't move it up again.
    again = client.post(f"/api/drills/{card['id']}/attempt", json={"move": "g8f6"}).json()
    assert again["card"]["box"] == 2 and again["card"]["attempts"] == 2
    assert client.get("/api/drills/stats").json()["due"] == 0
    assert client.post(f"/api/drills/{card['id']}/attempt", json={"move": "e1e2"}).status_code == 400

    insights = client.get("/api/insights").json()
    assert insights["games"] == 1 and insights["causes"][0]["motif"] == "fork"
