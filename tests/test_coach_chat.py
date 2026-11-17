"""Follow-up questions to the coach: engine checks, grounding, the call loop and the conversation API,
with a fake Claude (no network, no API key, no subprocess) and a fake engine."""

from __future__ import annotations

import json

import chess
import pytest
from fastapi.testclient import TestClient

from chess_analysis_engine.api.app import create_app
from chess_analysis_engine.api.routes import coach as coach_routes
from chess_analysis_engine.api.schemas import Settings
from chess_analysis_engine.api.state import AppState
from chess_analysis_engine.explain.coach_chat import (
    CHAT_SCHEMA,
    CHAT_SYSTEM_PROMPT,
    NO_ANSWER,
    ChatThread,
    ask,
    check_answer,
    grounding_for,
    lookup_json,
    run_lookups,
    scan_question,
)
from chess_analysis_engine.explain.coach_cli import ClaudeCodeClient
from chess_analysis_engine.explain.coach_llm import Grounding
from chess_analysis_engine.models import EngineLine, Explanation, MoveReview, Score, color_name
from test_coach import FakeClaude, FakeClient, cli_result, reply

# After 3...Qf6 4. Nc3 the queen can take on f2 with check, a move that exists only in that line.
QF6_ANSWER = "After 3...Qf6 your queen on f6 guards f7, and if 4. Nc3 then 4...Qxf2+ even wins a pawn."


class FakeEngine:
    """Stands in for Stockfish's review of a move: a "good" move, answered by the given reply line."""

    def __init__(self, replies: dict[str, list[str]] | None = None):
        self.replies = replies or {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, board: chess.Board, move: chess.Move) -> MoveReview:
        self.calls.append((board.fen(), move.uci()))
        san = board.san(move)
        after = board.copy()
        after.push(move)
        reply_uci = self.replies.get(move.uci()) or [next(iter(after.legal_moves)).uci()]
        line = after.copy()
        reply_san = []
        for uci in reply_uci:
            reply_san.append(line.san(chess.Move.from_uci(uci)))
            line.push_uci(uci)
        return MoveReview(
            ply=board.ply() + 1,
            move_number=board.fullmove_number,
            color=color_name(board.turn),
            san=san,
            uci=move.uci(),
            fen_before=board.fen(),
            fen_after=after.fen(),
            eval_before=Score(cp=-30),
            eval_after=Score(cp=-20),
            win_before=45.0,
            win_after=47.0,
            ep_before=0.55,
            ep_after=0.53,
            ep_loss=0.02,
            accuracy=95.0,
            classification="good",
            refutation=EngineLine(uci=reply_uci, san=reply_san, score=Score(cp=-20), depth=18),
            explanation=Explanation(headline=f"{san} holds everything together."),
        )


def answer(text: str = "", analyze: list | None = None):
    return reply({"answer": text, "analyze": analyze or []})


def asked(move, question, *replies, lookup=None, thread=None, db=None, shown=None):
    client = FakeClient(*replies)
    thread = thread if thread is not None else ChatThread()
    turn = ask(
        move,
        "black",
        question,
        thread,
        client=client,
        model="claude-opus-5-5",
        effort="medium",
        lookup=lookup,
        db=db,
        shown=shown,
    )
    return turn, thread, client


def first_text(call: dict) -> str:
    return "\n".join(block["text"] for block in call["messages"][0]["content"])


# --- engine checks ------------------------------------------------------------------------------


def test_moves_in_the_question_are_picked_out(move):
    assert scan_question("Why not 3...Qf6 instead?", move) == [("before", ["Qf6"])]
    assert scan_question("And what if White plays 4. Nc3?", move) == [("after", ["Nc3"])]
    assert scan_question("Could I castle with O-O here?", move) == []  # not legal yet
    # Already analysed: the move played, the best move and the opponent's best reply.
    assert scan_question("Why is Nf6 bad, why is 3...g6 good, and why Qxf7?", move) == []
    # A bare pawn move is read as a square; a numbered one is a move.
    assert scan_question("Is the pawn on d6 important?", move) == []
    assert scan_question("What about 3...d6?", move) == [("before", ["d6"])]
    assert scan_question("Why not Nf3?", move) == [("after", ["Nf3"])]  # Black has no Nf3: White's
    assert len(scan_question("Qe7? Qf6? Nd4? Nb4?", move)) == 2


def test_lookups_are_checked_once_and_illegal_ones_noted(move):
    engine = FakeEngine()
    thread = ChatThread()
    indexes, notes = run_lookups(
        [("before", ["3...Qf6!?"]), ("before", ["Bxf2+"]), ("after", ["4. Nc3", "Nd4"])], move, engine, thread
    )
    assert indexes == [0, 1] and len(engine.calls) == 2
    assert notes == ["Bxf2+ is not a legal move there (from the position before the move played)"]
    assert thread.lookups[0].sans == ["Qf6"] and thread.lookups[0].uci == ["d8f6"]
    # A two-move line: the last move is the one reviewed, from the position after the first.
    assert thread.lookups[1].sans == ["Nc3", "Nd4"] and thread.lookups[1].review.san == "Nd4"
    again, _ = run_lookups([("before", ["Qf6"])], move, engine, thread)
    assert again == [0] and len(engine.calls) == 2 and len(thread.lookups) == 2

    line = thread.lookups[0].line()
    assert line.start_fen == move.fen_before and line.uci[0] == "d8f6" and len(line.uci) == 2
    check = lookup_json(thread.lookups[0], "black")
    assert check["line"] == "3...Qf6" and check["last_move"]["label"] == "good"
    assert check["chances"]["after_percent"] == 53  # Black's view of White's 47%
    json.dumps(check)


def test_engine_failure_becomes_a_note(move):
    def broken(board, played):
        raise RuntimeError("engine crashed")

    indexes, notes = run_lookups([("before", ["Qf6"])], move, broken, ChatThread())
    assert indexes == [] and notes == ["The engine couldn't check 3...Qf6"]


# --- grounding ----------------------------------------------------------------------------------


def test_answers_may_use_engine_checks_and_quote_the_player(move):
    engine = FakeEngine({"d8f6": ["b1c3", "f6f2"]})
    thread = ChatThread()
    assert check_answer(QF6_ANSWER, grounding_for(move, "black", thread, []))  # nothing checked yet
    run_lookups([("before", ["Qf6"])], move, engine, thread)
    assert check_answer(QF6_ANSWER, grounding_for(move, "black", thread, [])) == []

    quoted = "Bxf2+ isn't possible here: there is no bishop on c5, and your bishop on f8 can't reach f2."
    question = "Why not Bxf2+ with my bishop on c5?"
    assert check_answer(quoted, grounding_for(move, "black", thread, []))
    assert check_answer(quoted, grounding_for(move, "black", thread, [question])) == []


def test_answers_get_the_narration_checks(move):
    grounding = grounding_for(move, "black", ChatThread(), [])
    for text, expected in [
        ("Your knight on d4 was the only defender.", "no such knight on d4"),
        ("The engine says +3.2 for White.", "evaluation number"),
        ("After 3...Nf6, 4. Qxe8 wins.", "the move 4. Qxe8"),
        ("", "must not be empty"),
    ]:
        assert any(expected in p for p in check_answer(text, grounding)), text
    assert check_answer("A pin is when a piece can't move without exposing a bigger one.", grounding) == []


def test_merged_grounding_keeps_the_original_rules(move):
    grounding = Grounding.of(move, "black")
    grounding.merge(Grounding.of(move, "black"))
    assert len(grounding.positions) > len(Grounding.of(move, "black").positions)
    assert grounding.best_san == "g6"  # untouched: only narrations must name the best move


# --- the call loop --------------------------------------------------------------------------------


def test_a_grounded_answer_is_kept_and_replayed(move, db):
    good = "4. Qxf7# is mate because your king on e8 is the only defender of f7."
    turn, thread, client = asked(move, "Why is it mate?", answer(good), db=db)
    assert turn.verified and turn.answer == good and turn.problems == [] and turn.lines == []

    call = client.calls[0]
    assert call["system"][0]["text"] == CHAT_SYSTEM_PROMPT
    assert call["output_config"]["format"]["schema"] == CHAT_SCHEMA
    first = call["messages"][0]["content"]
    assert first[0]["cache_control"] == {"type": "ephemeral"}
    payload = json.loads(first[0]["text"])
    assert payload["move"]["played"] == "3...Nf6" and payload["engine_checks"] is False
    assert "explanation_shown" not in payload
    assert first[1]["text"] == "The player asks: Why is it mate?"

    # The next question replays the first one and its answer, after the same opening block.
    _, thread, client = asked(move, "What should I remember?", answer("Guard f7."), thread=thread)
    messages = client.calls[0]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == first
    assert json.loads(messages[1]["content"]) == {"answer": good, "analyze": []}
    assert messages[2]["content"][0]["text"] == "The player asks: What should I remember?"
    assert len(thread.turns) == 2

    (usage,) = db.coach_usage()
    assert usage["calls"] == 1 and usage["rejected"] == 0


def test_a_move_in_the_question_is_checked_before_asking(move):
    engine = FakeEngine({"d8f6": ["b1c3", "f6f2"]})
    turn, _, client = asked(move, "Why not 3...Qf6?", answer(QF6_ANSWER), lookup=engine)
    assert turn.verified and len(client.calls) == 1 and turn.lookups == [0]
    assert turn.lines[0].san == ["Qf6", "Nc3", "Qxf2+"] and turn.labels == ["3...Qf6"]
    text = first_text(client.calls[0])
    assert "Engine checks:" in text and '"line": "3...Qf6"' in text
    assert json.loads(client.calls[0]["messages"][0]["content"][0]["text"])["engine_checks"] is True


def test_claude_can_ask_for_one_round_of_engine_checks(move, db):
    engine = FakeEngine({"c6b4": ["c2c3"]})
    request = [{"from": "before", "moves": ["Nb4"]}, {"from": "before", "moves": ["Kxe2"]}]
    good = "3...Nb4 attacks c2, but after 4. c3 the knight has to go back."
    turn, thread, client = asked(
        move,
        "Couldn't I attack something with my knight?",
        answer("", request),
        answer(good, [{"from": "before", "moves": ["Qe7"]}]),  # a second request is ignored
        lookup=engine,
        db=db,
    )
    assert turn.verified and turn.answer == good and len(client.calls) == 2
    assert engine.calls == [(move.fen_before, "c6b4")]
    assert turn.notes == ["Kxe2 is not a legal move there (from the position before the move played)"]
    results = client.calls[1]["messages"][-1]["content"]
    assert "Engine checks:" in results and "Not checked:" in results and "No more engine checks" in results
    assert db.coach_usage()[0]["calls"] == 2 and db.coach_usage()[0]["rejected"] == 0

    # Replayed later, the checks appear with the question they were made for.
    _, _, later = asked(move, "And then?", answer("Then the knight retreats."), thread=thread, lookup=engine)
    assert "3...Nb4" in later.calls[0]["messages"][0]["content"][1]["text"]


def test_without_an_engine_claude_answers_from_the_review(move):
    turn, _, client = asked(move, "Why not 3...Qf6?", answer("Even 3...Qf6 would have covered f7."))
    assert turn.verified and turn.lookups == [] and "Engine checks" not in first_text(client.calls[0])


def test_an_answer_that_fails_twice_is_not_shown(move, db):
    bad = answer("Your knight on d4 was the only defender.")
    turn, thread, client = asked(move, "Why?", bad, bad, db=db)
    assert not turn.verified and turn.answer == NO_ANSWER and len(client.calls) == 2
    assert any("no such knight on d4" in p for p in turn.problems)
    assert "knight on d4" in client.calls[1]["messages"][-1]["content"]
    assert all("knight on d4" not in t.answer for t in thread.turns)
    assert db.coach_usage()[0]["rejected"] == 2

    # Asking the same question again replaces the failed turn; the replay never quotes the bad text.
    turn, thread, client = asked(move, "Why?", answer("Because f7 was weak."), thread=thread)
    assert turn.verified and len(thread.turns) == 1


def test_a_corrected_answer_is_accepted(move):
    turn, _, client = asked(move, "Why?", answer("The engine says +3.2."), answer("Because f7 was weak."))
    assert turn.verified and turn.answer == "Because f7 was weak." and len(client.calls) == 2


def test_the_coach_narration_on_screen_is_included(move):
    shown = Explanation(headline="Your knight blocked nothing.", source="coach")
    _, _, client = asked(move, "What did you mean?", answer("That f7 stayed weak."), shown=shown)
    payload = json.loads(client.calls[0]["messages"][0]["content"][0]["text"])
    assert payload["explanation_shown"]["headline"] == "Your knight blocked nothing."


def test_a_refusal_is_not_retried(move):
    turn, _, client = asked(move, "Why?", reply(None, stop_reason="refusal"))
    assert not turn.verified and len(client.calls) == 1 and "declined to answer" in turn.problems[0]


# --- API ----------------------------------------------------------------------------------------


def test_chat_api(db, move, monkeypatch):
    client = FakeClient(answer("Because f7 was weak."), answer("Guard it."), answer("Again."))
    state = AppState(db=db, coach_clients={"api": client})
    body = {"move": move.model_dump(mode="json"), "user_color": "black", "question": "Why?"}
    which = {"fen_before": move.fen_before, "uci": move.uci, "user_color": "black"}
    with TestClient(create_app(state)) as http:
        assert http.post("/api/coach/chat", json=body).status_code == 409  # coach off
        settings = http.get("/api/settings").json()
        http.put("/api/settings", json={**settings, "coach_enabled": True})

        assert http.post("/api/coach/chat/thread", json=which).json() == {"turns": [], "limit": 20}
        view = http.post("/api/coach/chat", json=body).json()
        assert [t["answer"] for t in view["turns"]] == ["Because f7 was weak."]
        assert len(http.post("/api/coach/chat/thread", json=which).json()["turns"]) == 1
        # The conversation belongs to the move and the side it's explained to.
        other = {**which, "user_color": "white"}
        assert http.post("/api/coach/chat/thread", json=other).json()["turns"] == []

        monkeypatch.setattr(coach_routes, "MAX_TURNS", 2)
        assert http.post("/api/coach/chat", json={**body, "question": "Then?"}).status_code == 200
        full = http.post("/api/coach/chat", json={**body, "question": "More?"})
        assert full.status_code == 409 and "clear the conversation" in full.json()["detail"]

        assert http.post("/api/coach/chat/clear", json=which).json()["turns"] == []
        assert http.post("/api/coach/chat", json={**body, "question": "More?"}).status_code == 200
        assert http.post("/api/coach/chat", json={**body, "question": "   "}).status_code == 422
        assert http.post("/api/coach/chat", json={**body, "question": "x" * 501}).status_code == 422


def test_chat_on_claude_code(move, tmp_path):
    first = {"answer": "4. Qxf7# is mate.", "analyze": []}
    claude = FakeClaude(cli_result(first), cli_result({"answer": "Guard f7.", "analyze": []}))
    client = ClaudeCodeClient("/usr/bin/claude", run=claude, cwd=tmp_path)
    thread = ChatThread()
    for question in ("Why is it mate?", "What should I remember?"):
        ask(move, "black", question, thread, client=client, model="claude-opus-5-5", effort="medium")
    assert [t.verified for t in thread.turns] == [True, True]

    argv = claude.calls[0]["argv"]
    assert argv[argv.index("--system-prompt") + 1] == CHAT_SYSTEM_PROMPT
    assert json.loads(argv[argv.index("--json-schema") + 1]) == CHAT_SCHEMA
    later = claude.calls[1]["input"]
    assert later.startswith(claude.calls[0]["input"])
    assert f"Your previous reply:\n{json.dumps(first)}" in later
    assert later.endswith("The player asks: What should I remember?")


# --- with Stockfish -------------------------------------------------------------------------------


@pytest.mark.engine
def test_engine_checks_with_stockfish(db, move, pool):
    state = AppState(db=db, interactive_pool=pool)
    settings = Settings(preset="quick")
    lookup = coach_routes._lookup(state, settings, "black")
    assert lookup is not None
    thread = ChatThread()
    indexes, notes = run_lookups([("before", ["Qf6"])], move, lookup, thread)
    assert indexes == [0] and notes == []
    review = thread.lookups[0].review
    assert review.san == "Qf6" and review.refutation and review.refutation.uci
    check = lookup_json(thread.lookups[0], "black")
    assert check["engine_reply"].startswith("4.")
    json.dumps(check)
