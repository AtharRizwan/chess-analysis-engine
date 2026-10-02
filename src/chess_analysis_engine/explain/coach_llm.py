"""Optional Claude "coach voice": the verified facts about a move, retold in a coach's words.

Facts come first. Claude only rewords what the deterministic analysis already found, and every reply is
checked against the position before anyone sees it:

- each move it names must be in one of the engine lines, or legal before or after the move;
- each "piece on square" it mentions must be true in one of the positions involved;
- it may not invent evaluations (no "+1.5", no centipawns, no winning chances other than the given ones);
- every fact id it cites must exist, and a mistake's better move must be the engine's move.

A reply that fails gets one correction round. If that fails too, the template explanation is used.
The `anthropic` package is an optional extra (`uv sync --extra coach`); nothing else imports this module's
dependencies, so the app works the same without it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import chess
from pydantic import BaseModel, Field

from chess_analysis_engine.explain.phrases import move_label, mover_win, numbered_line
from chess_analysis_engine.explain.templates import Voice, build_explanation, eval_words
from chess_analysis_engine.models import (
    Color,
    EngineLine,
    Explanation,
    ExplanationSection,
    LineRef,
    MoveReview,
)

log = logging.getLogger(__name__)

PROMPT_VERSION = 1  # part of the cache key: bump it when the prompt or the checks change
MAX_TOKENS = 16000  # thinking counts toward this on Opus 5.5 (it can't be turned off there)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Server-side refusal fallback ("default" form) is offered on the Claude 5 family.
FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5", "claude-sonnet-5", "claude-mythos-5")
# Dollars per million tokens: input, output, cache read, cache write (5-minute TTL is 1.25x input).
PRICES: dict[str, tuple[float, float, float, float]] = {"claude-opus-5-5": (4.0, 20.0, 0.20, 5.0)}
BAD = ("inaccuracy", "mistake", "miss", "blunder")


class CoachNote(BaseModel):
    """What Claude writes for one move (the JSON schema below mirrors these fields)."""

    headline: str
    what_happened: str
    why: str
    better_move: str = ""
    lesson: str
    fact_ids_used: list[str] = Field(default_factory=list)


COACH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One sentence: the heart of the matter."},
        "what_happened": {"type": "string", "description": "What the move did and what follows."},
        "why": {"type": "string", "description": "The mechanism: why it fails or why it works."},
        "better_move": {
            "type": "string",
            "description": "What was better and what it achieves; empty if the move was the best one.",
        },
        "lesson": {"type": "string", "description": "The general idea to remember, with how to spot it."},
        "fact_ids_used": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "what_happened", "why", "better_move", "lesson", "fact_ids_used"],
    "additionalProperties": False,
}


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, other: Usage) -> Usage:
        return Usage(**{k: getattr(self, k) + getattr(other, k) for k in Usage.model_fields})


class Narration(BaseModel):
    """A move's explanation from the coach, or the template one when the coach's version didn't check out."""

    explanation: Explanation
    source: Literal["coach", "template"]
    model: str
    cached: bool = False
    problems: list[str] = Field(default_factory=list)  # why the coach's text was rejected, if it was
    usage: Usage = Field(default_factory=Usage)


class CoachError(Exception):
    """The Claude API couldn't be used; `status` is the HTTP status to report."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# --- prompt ---------------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a chess coach reviewing one move from a player's own game. The player wants to understand the \
move, not just see a label: what happened, why it works or fails, what was better and what to remember \
next time. Write for an adult who plays regularly and wants the real reasons, explained clearly. Never \
talk down to them and never mention ratings or skill levels.

You will receive a JSON description of the move. Everything in it was computed and verified by a chess \
engine and a rules-based analyser:

- "move": the move played, its label (best, excellent, good, inaccuracy, mistake, miss, blunder, \
great, brilliant, book, forced), the game phase and how hard the better move was to find.
- "chances": the mover's winning chances before and after the move, in percent, and the same in words.
- "position_before" and "position_after": FEN and a diagram (uppercase = White, lowercase = Black, \
"." = empty; rank 8 at the top).
- "lines": the engine's best line from the position before the move, the opponent's best reply line \
after it ("refutation") and other strong options. Lines are in standard algebraic notation with move \
numbers.
- "facts": the verified reasons, each with an id, a kind (for example hangs_piece, allows_tactic, \
ignored_threat, missed_tactic, best_parries_threat, positional), the squares and pieces involved and \
often the line that proves it.
- "draft": the explanation written from those facts by templates. It is correct but mechanical. Your \
job is to say the same things the way a good coach would: connected, concrete and memorable.
- "legal_moves_before" and "legal_moves_after": every legal move in those two positions.

Rules. Your reply is checked automatically and rejected if it breaks any of them:

1. Only use what the input says. Do not add tactics, threats, plans or evaluations that are not in the \
facts, lines or draft. If the facts don't give a clear reason, say plainly that the engine's line is \
the reason and walk through it.
2. Only name moves that appear in the lines or in the legal move lists, written exactly as they are \
there (same SAN, including the piece letter, capture "x", disambiguation and promotion). Put a move \
number in front of a move when that helps ("10. Nc7+", "9...Na6").
3. When you say a piece is on, at or from a square ("the knight on c7", "your rook on a8"), it must \
really be there in one of the positions given (before, after, or along one of the lines).
4. No evaluation numbers: no "+1.5", no centipawns, no pawn-unit scores, no percentages except the \
winning chances given in "chances". Use the words in "chances" instead ("clearly better", "winning").
5. "fact_ids_used" lists the ids of the facts your text relies on, and only ids that exist in "facts".
6. When the move was a mistake of any size and the engine's best move differs from it, "better_move" \
must name that best move and say what it achieves according to the facts or the best line. When the \
played move was the best move, leave "better_move" empty.
7. Follow the "voice" setting: either speak to the player as "you" (their opponent is "your \
opponent"), or, when no player is set, name the sides as White and Black.

Fields:
- headline: one sentence that captures the key point, under 25 words.
- what_happened: two to four sentences on what the move did and what the opponent can do next, using \
the refutation line when there is one.
- why: one to three sentences on the mechanism: the tactic, the undefended piece, the ignored threat, \
the weakened square, or why the move works when it's good.
- better_move: two to three sentences on the better move and why it's better, or empty.
- lesson: one or two sentences with the general principle and a concrete habit to spot it next time, \
for example "Before every move, check which of your pieces your move leaves undefended."

Plain prose only: no markdown, no bullet points, no headings inside the fields. Keep the whole reply \
under 220 words. Concrete beats general: name the squares and pieces involved.
"""


def _diagram(fen: str) -> str:
    board = chess.Board(fen)
    rows = []
    for rank in range(7, -1, -1):
        cells = []
        for file in range(8):
            piece = board.piece_at(chess.square(file, rank))
            cells.append(piece.symbol() if piece else ".")
        rows.append(f"{rank + 1} {' '.join(cells)}")
    rows.append("  a b c d e f g h")
    return "\n".join(rows)


def _line_json(
    line: LineRef | EngineLine | None, start_fen: str | None = None, plies: int = 10
) -> str | None:
    if line is None or not line.san:
        return None
    fen = start_fen if start_fen is not None else line.start_fen  # type: ignore[union-attr]
    text = numbered_line(fen, line.san, plies)
    return text + (" …" if len(line.san) > plies else "")


def _legal_sans(fen: str) -> list[str]:
    board = chess.Board(fen)
    return sorted(board.san(move) for move in board.legal_moves)


def _player(user: Color | None, color: Color) -> str:
    return Voice(user).who(color)


def build_payload(move: MoveReview, user: Color | None) -> dict[str, Any]:
    """The user message: everything Claude may use, and nothing else."""
    v = Voice(user)
    explanation = move.explanation or build_explanation(move, move.facts, user)
    perspective: Color = user or move.color
    facts = []
    for fact in move.facts:
        item: dict[str, Any] = {
            "id": fact.id,
            "kind": fact.kind,
            "motif": fact.motif,
            "side": _player(user, fact.actor) if fact.actor else None,
            "squares": fact.squares,
            "material": fact.material,
            "details": fact.data,
            "line": _line_json(fact.line),
        }
        facts.append({k: val for k, val in item.items() if val not in (None, [], {})})
    return {
        "voice": (
            f"Speak to the player of {user.capitalize()} as 'you'."
            if user
            else "No player is set: name the sides as White and Black."
        ),
        "move": {
            "played": move_label(move.move_number, move.color, move.san),
            "by": _player(user, move.color),
            "label": move.classification,
            "phase": move.phase,
            "difficulty_of_better_move": move.difficulty,
            "seconds_spent": round(move.clock.spent) if move.clock and move.clock.spent is not None else None,
        },
        "chances": {
            "for": _player(user, perspective),
            "before_percent": round(mover_win(move.win_before, perspective)),
            "after_percent": round(mover_win(move.win_after, perspective)),
            "before_words": eval_words(move.eval_before, move.color, v),
            "after_words": eval_words(move.eval_after, move.color, v),
        },
        "position_before": {
            "fen": move.fen_before,
            "diagram": _diagram(move.fen_before),
            "to_move": move.color,
        },
        "position_after": {"fen": move.fen_after, "diagram": _diagram(move.fen_after)},
        "lines": {
            "best": _line_json(move.best, move.fen_before),
            "refutation": _line_json(move.refutation, move.fen_after),
            "alternatives": [_line_json(alt, move.fen_before, 6) for alt in move.alternatives[1:3]],
        },
        "facts": facts,
        "draft": {
            "headline": explanation.headline,
            "sections": [{"title": s.title, "text": s.text} for s in explanation.sections],
            "lesson": explanation.lesson,
        },
        "legal_moves_before": _legal_sans(move.fen_before),
        "legal_moves_after": _legal_sans(move.fen_after),
    }


# --- grounding checks -------------------------------------------------------------------------

_SAN_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:(?P<num>\d+)\s*(?P<sep>\.\s*\.\.|\.…|…|\.)\s*|(?P<dots>\.\.\.|…)\s*)?"
    r"(?P<san>O-O-O|O-O|0-0-0|0-0|[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?"
    r"|[a-h]x[a-h][1-8](?:=[QRBN])?|[a-h][1-8](?:=[QRBN])?)"
    r"[+#]?[!?]*"
    r"(?![A-Za-z0-9])"
)
_PIECE_RE = re.compile(
    r"\b(?:(?P<owner>white's|black's|white|black|your opponent's|the opponent's|opponent's|your|their)\s+)?"
    r"(?P<piece>king|queen|rook|bishop|knight|pawn)s?\s+(?P<prep>on|at|from|to)\s+"
    r"(?P<squares>[a-h][1-8](?:(?:\s*,\s*|\s+and\s+|\s+or\s+)[a-h][1-8])*)\b",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b)", re.IGNORECASE)
_SIGNED_RE = re.compile(r"(?<![\w.])[+−-]\d+(?:\.\d+)?(?![\w-])")
_DECIMAL_RE = re.compile(r"(?<![\w.+−-])\d+\.\d+(?![\w.])")  # unsigned: signed ones are reported once
_CENTIPAWN_RE = re.compile(r"\b(?:centipawns?|cp)\b", re.IGNORECASE)
_MATE_IN_RE = re.compile(r"\bmate in (\d+)\b", re.IGNORECASE)
_PIECES = {
    "king": chess.KING,
    "queen": chess.QUEEN,
    "rook": chess.ROOK,
    "bishop": chess.BISHOP,
    "knight": chess.KNIGHT,
    "pawn": chess.PAWN,
}


def _norm_san(san: str) -> str:
    return san.rstrip("+#!?").replace("0", "O")


def _side(match: re.Match[str]) -> chess.Color | None:
    """Whose move a SAN match names, when it's numbered: "4. a5" is White's, "4...a5" or "…a5" Black's."""
    if match.group("num"):
        return chess.WHITE if match.group("sep") == "." else chess.BLACK
    return chess.BLACK if match.group("dots") else None


def _is_square(match: re.Match[str]) -> bool:
    """A bare "e4" without a move number is a square, not a pawn move."""
    numbered = match.group("num") or match.group("dots")
    return not numbered and re.fullmatch(r"[a-h][1-8]", match.group("san")) is not None


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


@dataclass
class Grounding:
    """What a narration of one move may refer to."""

    positions: list[chess.Board]
    sans: dict[str, set[chess.Color]]  # move -> the sides that play it somewhere in the lines/positions
    destinations: set[tuple[int, int]]  # (piece type, square) reachable by a legal move before/after
    fact_ids: set[str]
    percents: list[float]
    mates: set[int]
    best_san: str | None  # the move "better_move" has to name, when there is one
    user: Color | None
    mover: Color
    problems: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, move: MoveReview, user: Color | None) -> Grounding:
        positions: list[chess.Board] = []
        sans: dict[str, set[chess.Color]] = {}

        def walk(fen: str, ucis: list[str]) -> None:
            board = chess.Board(fen)
            positions.append(board.copy(stack=False))
            for uci in ucis:
                try:
                    played = chess.Move.from_uci(uci)
                    sans.setdefault(_norm_san(board.san(played)), set()).add(board.turn)
                    board.push(played)
                except (ValueError, AssertionError):
                    return
                positions.append(board.copy(stack=False))

        walk(move.fen_before, [move.uci])
        for line in [move.best, *move.alternatives]:
            if line:
                walk(move.fen_before, line.uci)
        if move.refutation:
            walk(move.fen_after, move.refutation.uci)
        for fact in move.facts:
            if fact.line:
                walk(fact.line.start_fen, fact.line.uci)

        # Moves the facts name in their details (e.g. the threat "13...Bxe5" from the null-move search).
        for fact in move.facts:
            for text in _strings(fact.data):
                for match in _SAN_RE.finditer(text):
                    if _is_square(match):
                        continue
                    side = _side(match)
                    sides = {side} if side is not None else {chess.WHITE, chess.BLACK}
                    sans.setdefault(_norm_san(match.group("san")), set()).update(sides)

        destinations: set[tuple[int, int]] = set()
        for fen in (move.fen_before, move.fen_after):
            board = chess.Board(fen)
            for legal in board.legal_moves:
                sans.setdefault(_norm_san(board.san(legal)), set()).add(board.turn)
                piece = board.piece_type_at(legal.from_square)
                if piece:
                    destinations.add((piece, legal.to_square))

        perspective: Color = user or move.color
        percents = [
            mover_win(move.win_before, perspective),
            mover_win(move.win_after, perspective),
            mover_win(move.win_before, move.color),
            mover_win(move.win_after, move.color),
        ]
        mates = {abs(s.mate) for s in (move.eval_before, move.eval_after) if s.mate}
        mates |= {
            abs(line.score.mate)
            for line in [move.best, move.refutation, *move.alternatives]
            if line and line.score.mate
        }
        mates |= {int(f.data["mate_in"]) for f in move.facts if isinstance(f.data.get("mate_in"), int)}

        best_san = None
        if move.best and move.best.uci and move.best.uci[0] != move.uci and move.classification in BAD:
            best_san = _norm_san(move.best.san[0])
        return cls(
            positions=positions,
            sans=sans,
            destinations=destinations,
            fact_ids={f.id for f in move.facts},
            percents=percents,
            mates=mates,
            best_san=best_san,
            user=user,
            mover=move.color,
        )

    def _owner_color(self, owner: str | None) -> chess.Color | None:
        if not owner:
            return None
        owner = owner.lower()
        if owner.startswith("white"):
            return chess.WHITE
        if owner.startswith("black"):
            return chess.BLACK
        if self.user is None:
            return None  # "your"/"their" without a player: can't tell whose
        user = chess.WHITE if self.user == "white" else chess.BLACK
        return user if owner == "your" else not user

    def _on_board(self, piece: int, square: int, color: chess.Color | None) -> bool:
        for board in self.positions:
            found = board.piece_at(square)
            if found and found.piece_type == piece and (color is None or found.color == color):
                return True
        return False

    def check_text(self, field_name: str, text: str) -> None:
        for match in _SAN_RE.finditer(text):
            if _is_square(match):
                continue  # a bare square ("the e4 square"), not a move
            sides = self.sans.get(_norm_san(match.group("san")), set())
            side = _side(match)
            if side is not None:
                sides = sides & {side}
            if not sides:
                self.problems.append(
                    f"{field_name}: the move {match.group(0).strip()} is not in any of the given lines or "
                    "legal move lists (for that side)"
                )
        for match in _PIECE_RE.finditer(text):
            piece = _PIECES[match.group("piece").lower()]
            color = self._owner_color(match.group("owner"))
            moving = match.group("prep").lower() == "to"
            for name in re.findall(r"[a-h][1-8]", match.group("squares")):
                square = chess.parse_square(name)
                if self._on_board(piece, square, color):
                    continue
                if moving and (piece, square) in self.destinations:
                    continue
                self.problems.append(
                    f"{field_name}: '{match.group(0)}' — there is no such {match.group('piece').lower()} "
                    f"on {name} in any of the positions"
                )
        for match in _PERCENT_RE.finditer(text):
            value = float(match.group(1))
            if not any(abs(value - allowed) <= 1.0 for allowed in self.percents):
                self.problems.append(
                    f"{field_name}: {match.group(0)} is not one of the given winning chances"
                )
        for regex, what in ((_SIGNED_RE, "an evaluation number"), (_DECIMAL_RE, "an evaluation number")):
            for match in regex.finditer(text):
                self.problems.append(f"{field_name}: '{match.group(0)}' looks like {what}; use words instead")
        if _CENTIPAWN_RE.search(text):
            self.problems.append(f"{field_name}: mentions centipawns; use words instead")
        for match in _MATE_IN_RE.finditer(text):
            if int(match.group(1)) not in self.mates:
                self.problems.append(f"{field_name}: '{match.group(0)}' doesn't match any mate in the lines")


def check_note(note: CoachNote, grounding: Grounding) -> list[str]:
    """Everything wrong with a note, as instructions Claude can act on; empty when it's grounded."""
    grounding.problems = []
    for name in ("headline", "what_happened", "why", "better_move", "lesson"):
        grounding.check_text(name, getattr(note, name))
    if not note.headline.strip() or not note.lesson.strip():
        grounding.problems.append("headline and lesson must not be empty")
    unknown = [i for i in note.fact_ids_used if i not in grounding.fact_ids]
    if unknown:
        grounding.problems.append(f"fact_ids_used has ids that don't exist: {', '.join(unknown)}")
    if grounding.best_san:
        mentioned = {_norm_san(m.group("san")) for m in _SAN_RE.finditer(note.better_move)}
        if grounding.best_san not in mentioned:
            grounding.problems.append(f"better_move must name the engine's best move, {grounding.best_san}")
    return list(dict.fromkeys(grounding.problems))


# --- calling Claude ---------------------------------------------------------------------------


def to_explanation(note: CoachNote, move: MoveReview, template: Explanation) -> Explanation:
    """The coach's note in the shape the UI shows, keeping the template's lines, arrows and hints."""
    lines = {s.title: s.line for s in template.sections}
    first_line = template.sections[0].line if template.sections else None
    better_title = next(
        (s.title for s in template.sections if s.title.startswith(("Better", "Even stronger"))), None
    )
    best_line = lines.get(better_title) if better_title else None
    if best_line is None and move.best and move.best.uci:
        best_line = LineRef(start_fen=move.fen_before, uci=move.best.uci[:8], san=move.best.san[:8])
    sections = [
        ExplanationSection(
            title="What happened", text=note.what_happened, fact_ids=note.fact_ids_used, line=first_line
        ),
        ExplanationSection(title="Why", text=note.why),
    ]
    if note.better_move.strip():
        best = move.best.san[0] if move.best and move.best.san else None
        title = better_title or (
            f"Better was {move_label(move.move_number, move.color, best)}" if best else "Better"
        )
        sections.append(ExplanationSection(title=title, text=note.better_move, line=best_line))
    return Explanation(
        headline=note.headline,
        sections=[s for s in sections if s.text.strip()],
        lesson=note.lesson,
        annotations=template.annotations,
        source="coach",
        hints=template.hints,
        focus=template.focus,
    )


def _usage(response: Any) -> Usage:
    u = getattr(response, "usage", None)
    return Usage(
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
    )


def estimate_cost(model: str, usage: Usage) -> float | None:
    prices = PRICES.get(model)
    if prices is None:
        return None
    inp, out, read, write = prices
    total = (
        usage.input_tokens * inp
        + usage.output_tokens * out
        + usage.cache_read_tokens * read
        + usage.cache_write_tokens * write
    )
    return total / 1_000_000


def cache_key(payload: dict[str, Any], model: str, effort: str) -> str:
    blob = json.dumps(
        {"v": PROMPT_VERSION, "model": model, "effort": effort, "payload": payload}, sort_keys=True
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def has_credentials(client: Any) -> bool:
    return bool(
        getattr(client, "api_key", None)
        or getattr(client, "auth_token", None)
        or getattr(client, "credentials", None)
    )


def make_client() -> Any:
    """An Anthropic client, or a CoachError saying what's missing."""
    try:
        import anthropic
    except ImportError as exc:
        raise CoachError(
            "The coach needs the optional 'anthropic' package: run `uv sync --extra coach`.", 503
        ) from exc
    client = anthropic.Anthropic(max_retries=2, timeout=180.0)
    if not has_credentials(client):
        raise CoachError(
            "No Anthropic credentials found. Start the server with ANTHROPIC_API_KEY set "
            "(or an `ant` profile) to use the coach.",
            503,
        )
    return client


def _create(client: Any, model: str, effort: str, messages: list[dict[str, Any]]) -> Any:
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": messages,
        "output_config": {"format": {"type": "json_schema", "schema": COACH_SCHEMA}, "effort": effort},
    }
    if model.startswith(FALLBACK_MODELS):
        # If a safety classifier ever declines (very unlikely for chess), the API re-runs the request on
        # Anthropic's recommended fallback model instead of returning a refusal.
        kwargs["betas"] = [FALLBACK_BETA]
        kwargs["fallbacks"] = "default"
    try:
        return client.beta.messages.create(**kwargs)
    except Exception as exc:  # map the SDK's typed errors to messages the UI can show
        raise _api_error(exc) from exc


def _api_error(exc: Exception) -> CoachError:
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if name == "AuthenticationError":
        return CoachError("The Anthropic API rejected the credentials (check ANTHROPIC_API_KEY).", 401)
    if name == "PermissionDeniedError":
        return CoachError(f"This API key can't use that model: {exc}", 403)
    if name == "NotFoundError":
        return CoachError(f"Unknown model — check the coach model in Settings. ({exc})", 400)
    if name == "RateLimitError":
        return CoachError("The Anthropic API is rate limiting requests; try again in a minute.", 429)
    if name in ("APIConnectionError", "APITimeoutError"):
        return CoachError("Couldn't reach the Anthropic API (network problem).", 502)
    if name == "BadRequestError":
        return CoachError(f"The Anthropic API refused the request: {exc}", 400)
    if status is not None:
        return CoachError(f"The Anthropic API returned an error ({status}): {exc}", 502)
    return CoachError(f"The coach failed: {exc}", 502)


def _read_note(response: Any) -> tuple[CoachNote | None, str | None]:
    """The note in a response, or why there isn't one. Checks stop_reason before touching the content."""
    reason = getattr(response, "stop_reason", None)
    if reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None)
        return None, f"Claude declined to narrate this move{f' ({category})' if category else ''}"
    if reason == "max_tokens":
        return None, "Claude ran out of room before finishing"
    text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
    if text is None:
        return None, "Claude's reply had no text"
    try:
        return CoachNote.model_validate_json(text), None
    except ValueError as exc:
        return None, f"Claude's reply wasn't valid JSON for the note: {exc}"


def narrate_move(
    move: MoveReview,
    user: Color | None,
    *,
    client: Any,
    model: str,
    effort: str,
    db: Any | None = None,
    refresh: bool = False,
) -> Narration:
    """Narrate one move with Claude, checked against the facts; falls back to the template explanation."""
    template = move.explanation or build_explanation(move, move.facts, user)
    payload = build_payload(move, user)
    key = cache_key(payload, model, effort)
    if db is not None and not refresh:
        cached = db.narration_get(key)
        if cached:
            narration = Narration.model_validate_json(cached)
            narration.cached = True
            narration.usage = Usage()
            return narration

    grounding = Grounding.of(move, user)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}
    ]
    usage = Usage()
    problems: list[str] = []
    narration: Narration | None = None
    for attempt in range(2):
        response = _create(client, model, effort, messages)
        call_usage = _usage(response)
        usage = usage.add(call_usage)
        note, failure = _read_note(response)
        problems = [failure] if failure else check_note(note, grounding)  # type: ignore[arg-type]
        log.info(
            "coach %s ply %s attempt %d: in=%d out=%d cache_read=%d cache_write=%d problems=%d",
            model,
            move.ply,
            attempt + 1,
            call_usage.input_tokens,
            call_usage.output_tokens,
            call_usage.cache_read_tokens,
            call_usage.cache_write_tokens,
            len(problems),
        )
        if db is not None:
            db.log_coach_usage(model, "ok" if not problems else "rejected", call_usage.model_dump())
        if not problems and note is not None:
            narration = Narration(
                explanation=to_explanation(note, move, template), source="coach", model=model, usage=usage
            )
            break
        if failure or attempt == 1:
            break  # a refusal or a truncated reply won't get better by asking again
        # One correction round: show Claude exactly what didn't check out.
        messages += [
            {"role": "assistant", "content": response.content},
            {
                "role": "user",
                "content": "Your note failed the automatic checks:\n- "
                + "\n- ".join(problems)
                + "\nRewrite the whole note so that it passes every rule. Keep everything else the same.",
            },
        ]
    if narration is None:
        narration = Narration(
            explanation=template, source="template", model=model, problems=problems, usage=usage
        )
    if db is not None:
        db.narration_put(key, model, narration.model_copy(update={"cached": False}).model_dump_json())
    return narration
