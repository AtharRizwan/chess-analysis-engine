"""The Claude coach's grounding checks, retry and fallback, with a fake client (no network, no API key)
and a fake Claude Code (no subprocess)."""

from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace

import chess
import pytest
from fastapi.testclient import TestClient

from chess_analysis_engine.api.app import create_app
from chess_analysis_engine.api.state import AppState
from chess_analysis_engine.explain.coach_cli import ClaudeCodeClient, make_cli_client
from chess_analysis_engine.explain.coach_llm import (
    COACH_SCHEMA,
    FALLBACK_BETA,
    SYSTEM_PROMPT,
    CoachError,
    CoachNote,
    Grounding,
    build_payload,
    check_note,
    estimate_cost,
    narrate_move,
)
from chess_analysis_engine.models import (
    EngineLine,
    Explanation,
    ExplanationSection,
    Fact,
    LineRef,
    MoveReview,
    Score,
)


def _fen_after(*sans: str) -> str:
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board.fen()


@pytest.fixture
def move() -> MoveReview:
    """3...Nf6?? walking into 4. Qxf7# (Black is the user)."""
    before = _fen_after("e4", "e5", "Bc4", "Nc6", "Qh5")
    after = _fen_after("e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6")
    mate_line = LineRef(start_fen=after, uci=["h5f7"], san=["Qxf7#"])
    return MoveReview(
        ply=6,
        move_number=3,
        color="black",
        san="Nf6",
        uci="g8f6",
        fen_before=before,
        fen_after=after,
        eval_before=Score(cp=30),
        eval_after=Score(mate=1),
        win_before=55.0,
        win_after=100.0,
        ep_before=0.47,
        ep_after=0.0,
        ep_loss=0.47,
        accuracy=0.0,
        classification="blunder",
        best=EngineLine(
            uci=["g7g6", "h5f3", "g8f6"], san=["g6", "Qf3", "Nf6"], score=Score(cp=-20), depth=18
        ),
        refutation=EngineLine(uci=["h5f7"], san=["Qxf7#"], score=Score(mate=1), depth=18),
        facts=[
            Fact(
                id="f1",
                kind="allows_mate",
                actor="white",
                squares=["f7"],
                line=mate_line,
                data={"mate_in": 1},
            ),
            Fact(id="f2", kind="best_defends", actor="black", squares=["f7"]),
        ],
        explanation=Explanation(
            headline="3...Nf6?? allows 4. Qxf7#, checkmate.",
            sections=[
                ExplanationSection(
                    title="What went wrong", text="It allows mate.", fact_ids=["f1"], line=mate_line
                ),
                ExplanationSection(title="Better was 3...g6", text="It blocks the queen."),
            ],
            lesson="Check every capture on the squares next to your king.",
            hints=["There's a threat against f7."],
            focus="f7",
        ),
    )


GOOD = {
    "headline": "3...Nf6?? lets White mate at once with 4. Qxf7#.",
    "what_happened": (
        "After 3...Nf6 the queen on h5 and the bishop on c4 both hit f7, and 4. Qxf7# is checkmate. "
        "Your winning chances drop from 45% to 0%."
    ),
    "why": "The f7 square was guarded only by your king on e8, so the queen takes it with the bishop's help.",
    "better_move": "3...g6 kicks the queen away first; after 4. Qf3 Nf6 the f7 pawn is safe.",
    "lesson": "When a queen and a bishop aim at a square next to your king, defend it before developing.",
    "fact_ids_used": ["f1"],
}


def note(**changes: object) -> CoachNote:
    return CoachNote.model_validate({**GOOD, **changes})


def test_grounded_note_passes(move):
    assert check_note(note(), Grounding.of(move, "black")) == []


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"what_happened": "After 3...Nf6, 4. Qxe8 wins on the spot."}, "the move 4. Qxe8"),
        ({"what_happened": "After 3...Nf6, 4...Qxf7 is mate."}, "the move 4...Qxf7"),  # White's move
        ({"why": "Your knight on d4 was the only defender."}, "no such knight on d4"),
        ({"why": "White's bishop on b5 pins the knight."}, "no such bishop on b5"),
        ({"why": "Your queen on h5 was loose."}, "no such queen on h5"),  # it's White's queen
        ({"what_happened": "The engine says +3.2 for White."}, "evaluation number"),
        ({"what_happened": "The engine says 3.2 for White."}, "evaluation number"),
        ({"what_happened": "That costs about 150 centipawns."}, "centipawns"),
        ({"what_happened": "Your chances fall to 12%."}, "12%"),
        ({"what_happened": "White has mate in 3."}, "mate in 3"),
        ({"fact_ids_used": ["f1", "f9"]}, "f9"),
        ({"better_move": "Defending f7 first was better."}, "must name the engine's best move"),
        ({"lesson": ""}, "must not be empty"),
    ],
)
def test_ungrounded_notes_are_rejected(move, changes, expected):
    problems = check_note(note(**changes), Grounding.of(move, "black"))
    assert any(expected in p for p in problems), problems


def test_each_problem_is_reported_once(move):
    assert check_note(note(why="The engine says +3.2."), Grounding.of(move, "black")) == [
        "why: '+3.2' looks like an evaluation number; use words instead"
    ]


def test_squares_moves_and_legal_alternatives(move):
    grounding = Grounding.of(move, "black")
    # A bare square is a square, not a pawn move; a numbered pawn move is a move and must exist.
    assert (
        check_note(note(why="Everything hinges on the f7 square and the e8 king's lack of room."), grounding)
        == []
    )
    assert any("the move 4. a5" in p for p in check_note(note(why="Even 4. a5 was possible."), grounding))
    assert check_note(note(why="Even 3...a5 was possible."), grounding) == []  # Black's move: legal
    assert check_note(note(why="Even 3…a5 was possible."), grounding) == []
    # Any legal move in the position before or after is fine to mention (e.g. a different defence).
    assert check_note(note(why="Even 3...Qe7 would have covered f7."), grounding) == []
    # "to" accepts a square a piece could legally move to.
    assert check_note(note(why="The queen could also go to f3 or e2."), grounding) == []


def test_colors_without_a_user(move):
    grounding = Grounding.of(move, None)
    text = note(what_happened="White's queen on h5 and White's bishop on c4 both hit f7; 4. Qxf7# follows.")
    assert check_note(text, grounding) == []
    assert check_note(note(why="Black's queen on h5 is attacked."), grounding)


def test_payload_contains_the_facts_and_the_draft(move):
    payload = build_payload(move, "black")
    assert payload["move"]["played"] == "3...Nf6"
    assert payload["lines"]["refutation"] == "4. Qxf7#"
    assert payload["lines"]["best"] == "3...g6 4. Qf3 Nf6"
    assert payload["chances"]["before_percent"] == 45 and payload["chances"]["after_percent"] == 0
    assert [f["id"] for f in payload["facts"]] == ["f1", "f2"]
    assert payload["draft"]["headline"].startswith("3...Nf6??")
    assert "g6" in payload["legal_moves_before"] and "Qxf7#" in payload["legal_moves_after"]
    json.dumps(payload)  # must be serializable as the user message


# --- the call loop, with a fake Anthropic client ------------------------------------------------


def reply(data: dict | None, stop_reason: str = "end_turn") -> SimpleNamespace:
    content = [SimpleNamespace(type="thinking", thinking="…")]
    if data is not None:
        content.append(SimpleNamespace(type="text", text=json.dumps(data)))
    usage = SimpleNamespace(
        input_tokens=1200, output_tokens=300, cache_read_input_tokens=900, cache_creation_input_tokens=0
    )
    return SimpleNamespace(stop_reason=stop_reason, stop_details=None, content=content, usage=usage)


class FakeClient:
    api_key = "test"

    def __init__(self, *replies: SimpleNamespace):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)


def test_valid_reply_becomes_the_coach_explanation(move, db):
    client = FakeClient(reply(GOOD))
    result = narrate_move(move, "black", client=client, model="claude-opus-5-5", effort="medium", db=db)
    assert result.source == "coach" and result.problems == []
    assert result.explanation.source == "coach"
    assert result.explanation.headline == GOOD["headline"]
    titles = [s.title for s in result.explanation.sections]
    assert titles == ["What happened", "Why", "Better was 3...g6"]
    # Lines, arrows and hints come from the verified analysis, not from Claude.
    assert result.explanation.sections[0].line.san == ["Qxf7#"]
    assert result.explanation.sections[2].line.san == ["g6", "Qf3", "Nf6"]
    assert result.explanation.hints == move.explanation.hints

    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"


def test_bad_reply_is_corrected_once(move, db):
    client = FakeClient(reply({**GOOD, "why": "Your knight on d4 was the only defender."}), reply(GOOD))
    result = narrate_move(move, "black", client=client, model="claude-opus-5-5", effort="medium", db=db)
    assert result.source == "coach"
    assert len(client.calls) == 2
    retry = client.calls[1]["messages"]
    assert retry[1]["role"] == "assistant" and retry[1]["content"][0].type == "thinking"
    assert "no such knight on d4" in retry[2]["content"]
    assert result.usage.input_tokens == 2400 and result.usage.cache_read_tokens == 1800
    usage = db.coach_usage()[0]
    assert usage["calls"] == 2 and usage["rejected"] == 1


def test_two_bad_replies_fall_back_to_the_template(move, db):
    bad = {**GOOD, "what_happened": "The engine says +3.2."}
    client = FakeClient(reply(bad), reply(bad))
    result = narrate_move(move, "black", client=client, model="claude-opus-5-5", effort="medium", db=db)
    assert result.source == "template"
    assert result.explanation == move.explanation
    assert any("evaluation number" in p for p in result.problems)


def test_refusal_and_truncation_are_not_retried(move, db):
    for stop, expected in (("refusal", "declined"), ("max_tokens", "ran out of room")):
        client = FakeClient(reply(None, stop_reason=stop))
        result = narrate_move(
            move, "black", client=client, model="claude-opus-5-5", effort="high", refresh=True, db=db
        )
        assert result.source == "template" and len(client.calls) == 1
        assert expected in result.problems[0]


def test_narrations_are_cached(move, db):
    client = FakeClient(reply(GOOD))
    first = narrate_move(move, "black", client=client, model="claude-opus-5-5", effort="medium", db=db)
    second = narrate_move(move, "black", client=client, model="claude-opus-5-5", effort="medium", db=db)
    assert not first.cached and second.cached and len(client.calls) == 1
    assert second.explanation == first.explanation and second.usage.input_tokens == 0
    # A different effort (or model, or voice) is a different narration.
    client.replies.append(reply(GOOD))
    narrate_move(move, "black", client=client, model="claude-opus-5-5", effort="low", db=db)
    assert len(client.calls) == 2


def test_models_without_server_fallback_get_a_plain_request(move):
    client = FakeClient(reply(GOOD))
    narrate_move(move, "black", client=client, model="claude-haiku-4-5", effort="medium")
    assert "fallbacks" not in client.calls[0] and "betas" not in client.calls[0]


def test_cost_estimate():
    from chess_analysis_engine.explain.coach_llm import Usage

    usage = Usage(input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=1_000_000)
    assert estimate_cost("claude-opus-5-5", usage) == pytest.approx(4.0 + 2.0 + 0.2)
    assert estimate_cost("some-other-model", usage) is None


# --- API ------------------------------------------------------------------------------------------


def test_coach_api(db, move):
    client = FakeClient(reply(GOOD))
    state = AppState(db=db, coach_clients={"api": client})
    with TestClient(create_app(state)) as http:
        status = http.get("/api/coach/status").json()
        assert status["enabled"] is False and status["ready"] is False and status["problem"] is None
        body = {"move": move.model_dump(mode="json"), "user_color": "black"}
        assert http.post("/api/coach/narrate", json=body).status_code == 409

        settings = http.get("/api/settings").json()
        http.put("/api/settings", json={**settings, "coach_enabled": True})
        assert http.get("/api/coach/status").json()["ready"] is True
        result = http.post("/api/coach/narrate", json=body).json()
        assert result["source"] == "coach" and result["explanation"]["source"] == "coach"
        assert http.post("/api/coach/narrate", json=body).json()["cached"] is True

        usage = http.get("/api/coach/status").json()["usage"]
        assert usage[0]["backend"] == "api" and usage[0]["calls"] == 1 and usage[0]["cost_usd"] > 0


def test_coach_without_credentials(db, move, monkeypatch, tmp_path):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "ANTHROPIC_CONFIG_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.config/anthropic profile either
    pytest.importorskip("anthropic")
    with TestClient(create_app(AppState(db=db))) as http:
        settings = http.get("/api/settings").json()
        http.put("/api/settings", json={**settings, "coach_enabled": True})
        status = http.get("/api/coach/status").json()
        assert status["ready"] is False and "credentials" in status["problem"]
        body = {"move": move.model_dump(mode="json"), "user_color": "black"}
        response = http.post("/api/coach/narrate", json=body)
        assert response.status_code == 503 and "ANTHROPIC_API_KEY" in response.json()["detail"]


# --- the Claude Code backend, with a fake `claude` command ----------------------------------------


def cli_result(note: dict | None = GOOD, **changes: object) -> str:
    """What `claude -p --output-format json --json-schema ...` prints."""
    usage = {
        "input_tokens": 1500,
        "output_tokens": 400,
        "cache_read_input_tokens": 5000,
        "cache_creation_input_tokens": 0,
    }
    result = {"type": "result", "subtype": "success", "is_error": False, "result": "", "usage": usage}
    return json.dumps({**result, "structured_output": note, **changes})


class FakeClaude:
    """Stands in for `subprocess.run` on the `claude` command: returns or raises the given outputs."""

    def __init__(self, *outputs: str | subprocess.CompletedProcess | Exception):
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append({"argv": argv, **kwargs})
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        if isinstance(output, str):
            return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")
        return output


def narrate_with(claude: FakeClaude, move: MoveReview, tmp_path, db=None):
    client = ClaudeCodeClient("/usr/bin/claude", run=claude, cwd=tmp_path)
    return narrate_move(
        move, "black", client=client, model="claude-opus-5-5", effort="medium", backend="claude_code", db=db
    )


def test_claude_code_narrates_through_claude_p(move, db, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CLAUDECODE", "1")
    claude = FakeClaude(cli_result())
    result = narrate_with(claude, move, tmp_path, db)
    assert result.source == "coach" and result.explanation.headline == GOOD["headline"]
    assert result.usage.input_tokens == 1500 and result.usage.cache_read_tokens == 5000

    (call,) = claude.calls
    argv = call["argv"]

    def flag(name: str) -> str:
        return argv[argv.index(name) + 1]

    assert argv[:2] == ["/usr/bin/claude", "-p"]
    assert flag("--output-format") == "json"
    assert json.loads(flag("--json-schema")) == COACH_SCHEMA
    assert flag("--system-prompt") == SYSTEM_PROMPT
    assert flag("--model") == "claude-opus-5-5" and flag("--effort") == "medium"
    assert flag("--tools") == ""  # no tools: Claude can only write the note
    assert {"--safe-mode", "--no-chrome", "--no-session-persistence"} <= set(argv)
    assert json.loads(call["input"]) == json.loads(json.dumps(build_payload(move, "black")))
    # The subscription is used, not an API key the server was started with; nested sessions are allowed.
    assert "ANTHROPIC_API_KEY" not in call["env"] and "CLAUDECODE" not in call["env"]
    assert call["cwd"] == tmp_path

    (usage,) = db.coach_usage()
    assert usage["backend"] == "claude_code" and usage["calls"] == 1


def test_claude_code_correction_round_quotes_the_reply(move, tmp_path):
    bad = {**GOOD, "why": "Your knight on d4 was the only defender."}
    claude = FakeClaude(cli_result(bad), cli_result())
    assert narrate_with(claude, move, tmp_path).source == "coach"
    retry = claude.calls[1]["input"]
    assert retry.startswith(claude.calls[0]["input"])
    assert f"Your previous reply:\n{json.dumps(bad)}" in retry and "no such knight on d4" in retry


@pytest.mark.parametrize(
    ("output", "status", "expected"),
    [
        (cli_result(None, is_error=True, result="Not logged in · Please run /login"), 401, "isn't signed in"),
        (
            cli_result(
                None, is_error=True, api_error_status=429, result="You've hit your limit · resets 5pm"
            ),
            429,
            "resets 5pm",
        ),
        (
            cli_result(None, is_error=True, api_error_status=404, result="model not found"),
            400,
            "Unknown model",
        ),
        (
            subprocess.CompletedProcess([], 1, stdout="", stderr="error: unknown option '--safe-mode'"),
            502,
            "unknown option",
        ),
        (subprocess.TimeoutExpired("claude", 180), 504, "didn't answer"),
        (FileNotFoundError("claude"), 503, "Couldn't start"),
    ],
)
def test_claude_code_errors(move, tmp_path, output, status, expected):
    with pytest.raises(CoachError) as caught:
        narrate_with(FakeClaude(output), move, tmp_path)
    assert caught.value.status == status and expected in str(caught.value)


def test_claude_code_without_a_valid_note_uses_the_template(move, tmp_path):
    output = {"type": "result", "subtype": "error_max_structured_output_retries", "is_error": True}
    claude = FakeClaude(json.dumps({**output, "errors": ["schema mismatch"], "usage": {}}))
    result = narrate_with(claude, move, tmp_path)
    assert result.source == "template" and len(claude.calls) == 1
    assert "no text" in result.problems[0]


def test_finding_claude_code(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(CoachError, match="isn't installed"):
        make_cli_client()
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/claude")
    with pytest.raises(CoachError, match="isn't signed in"):
        make_cli_client(run=FakeClaude(json.dumps({"loggedIn": False})))
    signed_in = FakeClaude(json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
    assert make_cli_client(run=signed_in).executable == "/usr/bin/claude"
    assert signed_in.calls[0]["argv"] == ["/usr/bin/claude", "auth", "status", "--json"]
    # When the status can't be read (an older Claude Code, say), the first narration reports any problem.
    assert make_cli_client(run=FakeClaude("error: unknown command 'auth'")).executable == "/usr/bin/claude"


def test_coach_api_on_claude_code(db, move, tmp_path):
    client = ClaudeCodeClient("/usr/bin/claude", run=FakeClaude(cli_result()), cwd=tmp_path)
    state = AppState(db=db, coach_clients={"claude_code": client})
    with TestClient(create_app(state)) as http:
        settings = http.get("/api/settings").json()
        assert settings["coach_backend"] == "api"
        http.put("/api/settings", json={**settings, "coach_enabled": True, "coach_backend": "claude_code"})
        status = http.get("/api/coach/status").json()
        assert status["ready"] is True and status["backend"] == "claude_code"
        body = {"move": move.model_dump(mode="json"), "user_color": "black"}
        assert http.post("/api/coach/narrate", json=body).json()["source"] == "coach"
        (usage,) = http.get("/api/coach/status").json()["usage"]
        assert usage["backend"] == "claude_code" and usage["calls"] == 1 and usage["cost_usd"] is None
