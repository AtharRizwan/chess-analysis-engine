"""Follow-up questions to the coach about one move: a short conversation, checked like the narrations.

The player asks; Claude answers from the same verified input the narration uses (the facts, the engine
lines, both positions and the legal moves), plus Stockfish's review of any other move the question is
about:

- a move written in the question ("why not 5...Qe7?") is checked before Claude is asked;
- Claude can ask for up to three more moves or short lines once per question ("why can't I take the
  knight?"), and answers when the results are in.

Every answer goes through the narration's grounding checks (moves, pieces on squares, no invented
evaluations). One that fails gets one correction round; if it fails again, the player is told there's
no answer that checks out, and the failing text is never shown or kept.

Conversations are kept per move (`thread_key`), with the engine checks made along the way, so later
questions can build on earlier answers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from typing import Any, Literal

import chess
from pydantic import BaseModel, ConfigDict, Field

from chess_analysis_engine.explain.coach_llm import (
    _SAN_RE,
    Grounding,
    Usage,
    _create,
    _is_square,
    _line_json,
    _norm_san,
    _side,
    _usage,
    build_payload,
    fact_json,
    read_reply,
)
from chess_analysis_engine.explain.phrases import move_label, mover_win, numbered_line
from chess_analysis_engine.explain.templates import Voice, build_explanation, eval_words
from chess_analysis_engine.models import Color, Explanation, LineRef, MoveReview

log = logging.getLogger(__name__)

Start = Literal["before", "after"]
# Reviews `move` in `board`, as the "why not this move?" explorer does (the API passes Stockfish in).
LookupFn = Callable[[chess.Board, chess.Move], MoveReview]

MAX_TURNS = 20  # questions per move before the conversation has to be cleared
MAX_QUESTION = 500  # characters
MAX_LOOKUPS = 3  # engine checks per round
MAX_SCANNED = 2  # moves picked out of the question itself
LINE_PLIES = 8  # moves of the engine's reply shown with a checked line
NO_ANSWER = (
    "The coach couldn't give an answer that checks out against the engine's analysis, so it isn't "
    "shown. Try asking again, or ask in a different way."
)
NO_ANSWER_REPLAY = "(No answer that passed the checks was given to this question.)"


class Lookup(BaseModel):
    """A move or short line Stockfish checked during the conversation; its last move is reviewed in full."""

    start: Start  # played from the position before the move under discussion, or after it
    start_fen: str
    sans: list[str]
    uci: list[str]
    review: MoveReview

    def line(self) -> LineRef:
        """The checked moves followed by the engine's reply, for the board."""
        reply = self.review.refutation
        uci, san = list(self.uci), list(self.sans)
        if reply and reply.uci:
            uci += reply.uci[:LINE_PLIES]
            san += reply.san[:LINE_PLIES]
        return LineRef(start_fen=self.start_fen, uci=uci, san=san)


class ChatTurn(BaseModel):
    question: str
    answer: str
    verified: bool = True  # False: no answer passed the checks, and `answer` says so
    problems: list[str] = Field(default_factory=list)  # why the last attempt was rejected, if it was
    notes: list[str] = Field(default_factory=list)  # engine checks that couldn't be made
    lookups: list[int] = Field(default_factory=list)  # indexes into ChatThread.lookups used for this turn
    lines: list[LineRef] = Field(default_factory=list)  # the checked lines, for the board
    labels: list[str] = Field(default_factory=list)  # each line's checked moves, numbered ("17. Nd6+ Kf8")
    usage: Usage = Field(default_factory=Usage)


class ChatThread(BaseModel):
    turns: list[ChatTurn] = Field(default_factory=list)
    lookups: list[Lookup] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start: Start = Field(alias="from")
    moves: list[str]


class ChatAnswer(BaseModel):
    """What Claude writes for one question (CHAT_SCHEMA mirrors these fields)."""

    answer: str = ""
    analyze: list[AnalyzeRequest] = Field(default_factory=list)


CHAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": "The answer to the player's question; empty when asking for engine checks.",
        },
        "analyze": {
            "type": "array",
            "description": "Moves or short lines for the engine to check before you answer (usually empty).",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string", "enum": ["before", "after"]},
                    "moves": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["from", "moves"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "analyze"],
    "additionalProperties": False,
}

CHAT_SYSTEM_PROMPT = """\
You are a chess coach. The player has read the explanation of one move from their own game and has \
follow-up questions about it. Answer each question directly, the way a good coach would at the board: \
concrete, honest and clear. Write for an adult who plays regularly and wants the real reasons. Never \
talk down to them and never mention ratings or skill levels.

The first message is a JSON description of the move. Everything in it was computed and verified by a \
chess engine and a rules-based analyser:

- "move": the move played, its label (best, excellent, good, inaccuracy, mistake, miss, blunder, \
great, brilliant, book, forced), the game phase and how hard the better move was to find.
- "chances": the mover's winning chances before and after the move, in percent, and the same in words.
- "position_before" and "position_after": FEN and a diagram (uppercase = White, lowercase = Black, \
"." = empty; rank 8 at the top).
- "lines": the engine's best line from the position before the move, the opponent's best reply line \
after it ("refutation") and other strong options, in standard algebraic notation with move numbers.
- "facts": the verified reasons, each with a kind (for example hangs_piece, allows_tactic, \
ignored_threat, missed_tactic, best_parries_threat, positional), the squares and pieces involved and \
often the line that proves it.
- "draft": the explanation written from those facts. "explanation_shown", when present, is the wording \
the player actually read.
- "legal_moves_before" and "legal_moves_after": every legal move in those two positions.
- "engine_checks": whether you can ask the engine to check other moves (see "analyze" below).

Each question comes as "The player asks: ...", sometimes followed by "Engine checks": Stockfish's review \
of other moves or short lines from this position, in the same terms (the moves, their label, the \
winning chances, the engine's reply line and the verified facts). You may use those like the rest of \
the input.

Rules. Your answer is checked automatically and rejected if it breaks any of them:

1. Claims about this game and these positions must come from the input or the engine checks. Do not \
add tactics, threats, plans or evaluations that are not there. General chess knowledge (what a pin is, \
why an exposed king is a problem) is fine, as long as you don't claim it applies here without support. \
If neither the input nor the engine checks answer the question, say so plainly instead of guessing.
2. Only name moves that appear in the lines, the engine checks, the legal move lists or the player's \
own question, written exactly as they are there (same SAN, including the piece letter, capture "x", \
disambiguation and promotion). Put a move number in front of a move when that helps ("10. Nc7+", \
"9...Na6").
3. When you say a piece is on, at or from a square ("the knight on c7", "your rook on a8"), it must \
really be there in one of the positions given (before, after, or along one of the lines or checks).
4. No evaluation numbers: no "+1.5", no centipawns, no pawn-unit scores, no percentages except the \
winning chances given. Use words instead ("clearly better", "winning").
5. Follow the "voice" setting: either speak to the player as "you" (their opponent is "your \
opponent"), or, when no player is set, name the sides as White and Black.

"analyze": when the question is about a move or line that is in neither the input nor the engine \
checks (for example "why can't I just take the knight?"), and "engine_checks" is true, don't guess. \
List it in "analyze" and leave "answer" empty; you get the engine's results and then answer. Each entry \
is a line of one to four moves in SAN, played either from the position before the move ("from": \
"before", so its first move is by the side that played the move) or from the position after it \
("from": "after", so its first move is the opponent's). At most three entries. You can ask once per \
question; after that "analyze" is ignored, so answer with what you have. Leave "analyze" empty when the \
input already covers the question.

"answer": plain prose, no markdown, bullet points or headings. Usually two to five sentences, never \
more than 150 words. Answer the question that was asked first, then add only what helps it. Name the \
squares and pieces involved. If the question has nothing to do with this move or with chess, say \
briefly that you can only help with this move.
"""


def thread_key(fen_before: str, uci: str, user: Color | None) -> str:
    """Which conversation a move has: the move itself, so a redone review keeps it."""
    return hashlib.sha256(f"{fen_before}|{uci}|{user or ''}".encode()).hexdigest()


# --- engine checks ----------------------------------------------------------------------------


def _start_fen(move: MoveReview, start: Start) -> str:
    return move.fen_before if start == "before" else move.fen_after


def scan_question(question: str, move: MoveReview) -> list[tuple[Start, list[str]]]:
    """Moves written in the question that the review hasn't already checked, legal before or after the move.

    Only unambiguous mentions count: piece moves, captures, castling and numbered moves. A bare "e5" is
    taken as a square ("the pawn on e5"); Claude can still ask for it to be checked.
    """
    covered = {"before": {_norm_san(move.san)}, "after": set[str]()}
    if move.best and move.best.san:
        covered["before"].add(_norm_san(move.best.san[0]))
    if move.refutation and move.refutation.san:
        covered["after"].add(_norm_san(move.refutation.san[0]))
    found: list[tuple[Start, list[str]]] = []
    for match in _SAN_RE.finditer(question):
        if _is_square(match):
            continue
        side = _side(match)
        for start in ("before", "after"):
            board = chess.Board(_start_fen(move, start))
            if side is not None and board.turn != side:
                continue
            try:
                san = board.san(board.parse_san(match.group("san")))
            except ValueError:
                continue
            if _norm_san(san) not in covered[start] and (start, [san]) not in found:
                found.append((start, [san]))
            break
    return found[:MAX_SCANNED]


def _clean_san(text: str) -> str:
    """'5...Qe7!?' -> 'Qe7': Claude and players write moves with numbers and marks."""
    text = re.sub(r"^\s*\d+\s*(?:\.\s*\.\.|\.…|…|\.)\s*|^\s*(?:\.\.\.|…)\s*", "", text)
    return text.strip().rstrip("!?")


def run_lookups(
    requests: list[tuple[Start, list[str]]],
    move: MoveReview,
    lookup: LookupFn,
    thread: ChatThread,
) -> tuple[list[int], list[str]]:
    """Check each requested line with the engine; returns the lookups' indexes in `thread` and notes on
    the ones that couldn't be checked. Lines already checked in this conversation are reused."""
    indexes: list[int] = []
    notes: list[str] = []
    for start, sans in requests[:MAX_LOOKUPS]:
        sans = [s for s in (_clean_san(s) for s in sans) if s][:4]
        if not sans:
            continue
        fen = _start_fen(move, start)
        where = "before" if start == "before" else "after"
        board = chess.Board(fen)
        canonical: list[str] = []
        ucis: list[str] = []
        try:
            for san in sans:
                played = board.parse_san(san)
                canonical.append(board.san(played))
                ucis.append(played.uci())
                board.push(played)
        except ValueError:
            shown = numbered_line(fen, [*canonical, san]) if canonical else san
            notes.append(f"{shown} is not a legal move there (from the position {where} the move played)")
            continue
        existing = next(
            (i for i, done in enumerate(thread.lookups) if done.start_fen == fen and done.uci == ucis), None
        )
        if existing is None:
            last = board.pop()
            try:
                review = lookup(board, last)
            except Exception as exc:  # an engine problem shouldn't lose the question
                log.warning("engine check of %s failed: %s", canonical, exc)
                notes.append(f"The engine couldn't check {numbered_line(fen, canonical)}")
                continue
            thread.lookups.append(Lookup(start=start, start_fen=fen, sans=canonical, uci=ucis, review=review))
            existing = len(thread.lookups) - 1
        if existing not in indexes:
            indexes.append(existing)
    return indexes, notes


def lookup_json(lookup: Lookup, user: Color | None) -> dict[str, Any]:
    """An engine check as Claude sees it: the line, the verdict on its last move and the verified facts."""
    review = lookup.review
    v = Voice(user)
    perspective: Color = user or review.color
    explanation = review.explanation or build_explanation(review, review.facts, user)
    best = review.best
    item: dict[str, Any] = {
        "line": numbered_line(lookup.start_fen, lookup.sans),
        "from": f"the position {lookup.start} the move played",
        "last_move": {
            "played": move_label(review.move_number, review.color, review.san),
            "by": v.who(review.color),
            "label": review.classification,
        },
        "chances": {
            "for": v.who(perspective),
            "before_last_move_percent": round(mover_win(review.win_before, perspective)),
            "after_percent": round(mover_win(review.win_after, perspective)),
            "after_words": eval_words(review.eval_after, review.color, v),
        },
        "engine_reply": _line_json(review.refutation, review.fen_after),
        "better_instead": (
            _line_json(best, review.fen_before) if best and best.uci and best.uci[0] != review.uci else None
        ),
        "facts": [fact_json(fact, user, with_id=False) for fact in review.facts],
        "summary": explanation.headline,
    }
    return {k: val for k, val in item.items() if val not in (None, [], {})}


def _checks_text(thread: ChatThread, indexes: list[int], notes: list[str], user: Color | None) -> str:
    parts = []
    if indexes:
        checks = [lookup_json(thread.lookups[i], user) for i in indexes]
        parts.append("Engine checks:\n" + json.dumps(checks, ensure_ascii=False, indent=1))
    if notes:
        parts.append("Not checked:\n- " + "\n- ".join(notes))
    return "\n\n".join(parts)


# --- the conversation -------------------------------------------------------------------------


def _shown_json(shown: Explanation | None) -> dict[str, Any] | None:
    if shown is None or shown.source != "coach":
        return None  # the template draft is in the payload already
    return {
        "headline": shown.headline,
        "sections": [{"title": s.title, "text": s.text} for s in shown.sections],
        "lesson": shown.lesson,
    }


def _question_text(question: str, checks: str) -> str:
    return f"The player asks: {question}" + (f"\n\n{checks}" if checks else "")


def build_messages(
    move: MoveReview,
    user: Color | None,
    thread: ChatThread,
    question: str,
    checks: str,
    *,
    engine: bool,
    shown: Explanation | None = None,
) -> list[dict[str, Any]]:
    """The conversation so far, replayed the same way every time so its start stays in the prompt cache."""
    payload = build_payload(move, user)
    if shown_json := _shown_json(shown):
        payload["explanation_shown"] = shown_json
    payload["engine_checks"] = engine
    first: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": json.dumps(payload, ensure_ascii=False, indent=1),
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages: list[dict[str, Any]] = []
    asks = [
        (_question_text(t.question, _checks_text(thread, t.lookups, t.notes, user)), t) for t in thread.turns
    ]
    for i, (text, turn) in enumerate([*asks, (_question_text(question, checks), None)]):
        block = {"type": "text", "text": text}
        messages.append({"role": "user", "content": [*first, block] if i == 0 else [block]})
        if turn is not None:
            answer = turn.answer if turn.verified else NO_ANSWER_REPLAY
            messages.append({"role": "assistant", "content": json.dumps({"answer": answer, "analyze": []})})
    return messages


def grounding_for(
    move: MoveReview, user: Color | None, thread: ChatThread, questions: list[str]
) -> Grounding:
    """What an answer may refer to: the move's own analysis, every engine check so far, and what the
    player wrote."""
    grounding = Grounding.of(move, user)
    grounding.best_san = None  # answers needn't name the best move
    for done in thread.lookups:
        grounding.merge(Grounding.of(done.review, user))
        grounding.add_line(done.start_fen, done.uci)
    for question in questions:
        grounding.allow_quoted(question)
    return grounding


def check_answer(answer: str, grounding: Grounding) -> list[str]:
    grounding.problems = []
    grounding.check_text("answer", answer)
    if not answer.strip():
        grounding.problems.append("answer must not be empty")
    return list(dict.fromkeys(grounding.problems))


def ask(
    move: MoveReview,
    user: Color | None,
    question: str,
    thread: ChatThread,
    *,
    client: Any,
    model: str,
    effort: str,
    backend: str = "api",
    lookup: LookupFn | None = None,
    db: Any | None = None,
    shown: Explanation | None = None,
) -> ChatTurn:
    """Answer one question about `move` and add the turn (and any engine checks) to `thread`.

    Asking again after an answer that didn't check out replaces that turn instead of adding one.
    """
    question = question.strip()[:MAX_QUESTION]
    if thread.turns and not thread.turns[-1].verified and thread.turns[-1].question == question:
        thread.turns.pop()

    indexes: list[int] = []
    notes: list[str] = []
    if lookup is not None:
        indexes, notes = run_lookups(scan_question(question, move), move, lookup, thread)
    messages = build_messages(
        move,
        user,
        thread,
        question,
        _checks_text(thread, indexes, notes, user),
        engine=lookup is not None,
        shown=shown,
    )

    usage = Usage()
    answer: str | None = None
    problems: list[str] = []
    looked_up = corrected = False
    while True:
        response = _create(client, model, effort, messages, system=CHAT_SYSTEM_PROMPT, schema=CHAT_SCHEMA)
        call_usage = _usage(response)
        usage = usage.add(call_usage)
        reply, failure = read_reply(response, ChatAnswer, "answer this question", "the answer")

        if reply and reply.analyze and lookup is not None and not looked_up and not corrected:
            # One round of engine checks, then Claude answers with the results in front of it.
            looked_up = True
            requests = [(r.start, r.moves) for r in reply.analyze]
            more, more_notes = run_lookups(requests, move, lookup, thread)
            indexes += [i for i in more if i not in indexes]
            notes += more_notes
            _log(db, model, backend, move, "lookup", call_usage, 0)
            checks = _checks_text(thread, more, more_notes, user) or "Nothing could be checked."
            messages += [
                {"role": "assistant", "content": response.content},
                {
                    "role": "user",
                    "content": checks + "\n\nNow answer the player's question. No more engine checks are "
                    "available for this question.",
                },
            ]
            continue

        grounding = grounding_for(move, user, thread, [t.question for t in thread.turns] + [question])
        problems = [failure] if failure else check_answer(reply.answer, grounding)  # type: ignore[union-attr]
        _log(db, model, backend, move, "ok" if not problems else "rejected", call_usage, len(problems))
        if not problems:
            answer = reply.answer.strip()  # type: ignore[union-attr]
            break
        if failure or corrected:
            break  # a refusal or a truncated reply won't get better by asking again
        corrected = True
        messages += [
            {"role": "assistant", "content": response.content},
            {
                "role": "user",
                "content": "Your answer failed the automatic checks:\n- "
                + "\n- ".join(problems)
                + '\nRewrite the whole answer so that it passes every rule. Leave "analyze" empty.',
            },
        ]

    turn = ChatTurn(
        question=question,
        answer=answer if answer is not None else NO_ANSWER,
        verified=answer is not None,
        problems=[] if answer is not None else problems,
        notes=notes,
        lookups=indexes,
        lines=[thread.lookups[i].line() for i in indexes],
        labels=[numbered_line(thread.lookups[i].start_fen, thread.lookups[i].sans) for i in indexes],
        usage=usage,
    )
    thread.turns.append(turn)
    return turn


def _log(
    db: Any | None, model: str, backend: str, move: MoveReview, outcome: str, usage: Usage, n: int
) -> None:
    log.info(
        "coach chat %s via %s ply %s (%s): in=%d out=%d cache_read=%d cache_write=%d problems=%d",
        model,
        backend,
        move.ply,
        outcome,
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
        n,
    )
    if db is not None:
        # An engine-check request isn't a rejected answer: it counts as an ordinary call.
        db.log_coach_usage(model, "rejected" if outcome == "rejected" else "ok", usage.model_dump(), backend)
