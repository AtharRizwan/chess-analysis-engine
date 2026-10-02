"""Turn verified facts into a short, concrete explanation in plain English."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import chess

from chess_analysis_engine.explain.phrases import numbered_line
from chess_analysis_engine.explain.principles import lesson_for
from chess_analysis_engine.facts.board import piece_name
from chess_analysis_engine.facts.mates import PATTERN_NAMES
from chess_analysis_engine.models import (
    Annotation,
    Color,
    Explanation,
    ExplanationSection,
    Fact,
    LineRef,
    MoveReview,
    Score,
    other,
)

MAX_LINE = 8

MOTIF_NAMES = {
    "fork": "fork",
    "pin": "pin",
    "skewer": "skewer",
    "discovered_attack": "discovered attack",
    "discovered_check": "discovered check",
    "double_check": "double check",
    "removal_of_defender": "removal of the defender",
    "trapped_piece": "trapped piece",
    "promotion": "promotion",
    "underpromotion": "underpromotion",
}

WRONG = (
    "allows_mate",
    "stalemate",
    "tablebase",
    "ignored_threat",
    "hangs_piece",
    "allows_tactic",
    "allows_attack",
    "loses_material",
    "positional",
    "opening_principle",
)
BETTER = (
    "missed_mate",
    "missed_material",
    "missed_tactic",
    "missed_win",
    "best_parries_threat",
    "best_avoids",
    "best_defends",
    "best_creates_threat",
)
GOOD = ("checkmate", "forces_mate", "executes_tactic", "sacrifice", "only_move", "parries_threat")


class Voice:
    """Who is "you": the user's side when known, otherwise colors are named."""

    def __init__(self, user: Color | None):
        self.user = user

    def who(self, color: Color) -> str:
        if self.user is None:
            return color.capitalize()
        return "you" if color == self.user else "your opponent"

    def whose(self, color: Color) -> str:
        if self.user is None:
            return f"{color.capitalize()}'s"
        return "your" if color == self.user else "their"

    def piece(self, p: dict[str, str] | None) -> str:
        if not p:
            return "a piece"
        return f"{self.whose(p['color'])} {p['piece']} on {p['square']}"  # type: ignore[arg-type]

    def pieces(self, items: list[dict[str, str]]) -> str:
        """'your pawns on b7 and f7 and your knight on c6': same-kind pieces grouped."""
        groups: dict[tuple[str, str], list[str]] = {}
        for p in items:
            groups.setdefault((p["color"], p["piece"]), []).append(p["square"])
        parts = []
        for (color, piece), squares in groups.items():
            plural = f"{piece}s" if len(squares) > 1 else piece
            parts.append(f"{self.whose(color)} {plural} on {and_join(squares)}")  # type: ignore[arg-type]
        return and_join(parts)


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def and_join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def tidy(text: str) -> str:
    return text.replace("….", "…").replace("… —", "… —")


def line_text(line: LineRef | None, max_plies: int = MAX_LINE) -> str:
    if line is None or not line.san:
        return ""
    text = numbered_line(line.start_fen, line.san, max_plies)
    return text + (" …" if len(line.san) > max_plies else "")


def captures(line: LineRef | None, actor: Color) -> tuple[list[str], list[str]]:
    """Pieces the actor takes and loses along a line, with even trades cancelled out."""
    if line is None:
        return [], []
    board = chess.Board(line.start_fen)
    actor_color = chess.WHITE if actor == "white" else chess.BLACK
    takes: list[str] = []
    loses: list[str] = []
    for uci in line.uci:
        move = chess.Move.from_uci(uci)
        if board.is_capture(move):
            victim = (
                chess.PAWN if board.is_en_passant(move) else board.piece_type_at(move.to_square) or chess.PAWN
            )
            (takes if board.turn == actor_color else loses).append(piece_name(victim))
        board.push(move)
    for name in list(takes):
        if name in loses:
            takes.remove(name)
            loses.remove(name)
    return takes, loses


def _count(names: list[str]) -> str:
    words = {1: "a", 2: "two", 3: "three", 4: "four"}
    order = ["queen", "rook", "bishop", "knight", "pawn"]
    parts = []
    for name in order:
        n = names.count(name)
        if n:
            parts.append(
                f"{words.get(n, str(n))} {name}{'s' if n > 1 else ''}"
                if name != "queen" or n > 1
                else "the queen"
            )
    return and_join(parts)


def _verb(subject: str, plural: str, singular: str) -> str:
    return f"{subject} {plural if subject == 'you' else singular}"


def with_move(m: MoveReview, line: LineRef | None) -> LineRef | None:
    """The opponent's line with the reviewed move in front, so trades it started cancel out."""
    if line is None:
        return None
    return LineRef(start_fen=m.fen_before, uci=[m.uci, *line.uci], san=[m.san, *line.san])


def outcome(line: LineRef | None, actor: Color, v: Voice) -> str:
    """'you lose a knight and a pawn' — what the actor's line costs the other side."""
    takes, loses = captures(line, actor)
    if not takes:
        return ""
    text = _verb(v.who(other(actor)), "lose", "loses") + f" {_count(takes)}"
    return text + (f" for {_count(loses)}" if loses else "")


def winnings(line: LineRef | None, actor: Color, v: Voice, would: bool = True) -> str:
    """'you would have won a rook' — what the actor's line gains."""
    takes, loses = captures(line, actor)
    if not takes:
        return ""
    who = v.who(actor)
    verb = "would have won" if would else ("win" if who == "you" else "wins")
    text = f"{who} {verb} {_count(takes)}"
    return text + (f" for {_count(loses)}" if loses else "")


def _dash(text: str) -> str:
    return f" — {text}" if text else ""


# --- one sentence per fact ------------------------------------------------------------------


def _tactic_phrase(motif: str, md: dict[str, Any], v: Voice) -> str:
    """'5. Nxe5, a discovered attack that unmasks their queen on d1 against your bishop on g4'."""
    key = md.get("key_move", "")
    targets = [v.piece(t) for t in md.get("targets", [])]
    piece = (md.get("piece") or {}).get("piece", "piece")
    if motif == "fork" and len(targets) >= 2:
        return f"{key}, a {piece} fork of {and_join(targets[:3])}"
    if motif == "pin" and targets:
        return f"{key}, pinning {targets[0]}{' to the king' if md.get('absolute') else ''}"
    if motif == "skewer" and len(targets) >= 2:
        return f"{key}, a skewer of {targets[0]} and {targets[1]}"
    if motif == "discovered_attack":
        hidden = v.piece(md.get("line_piece")) if md.get("line_piece") else "the piece behind it"
        target = targets[0] if targets else "material"
        return f"{key}, a discovered attack that unmasks {hidden} against {target}"
    if motif == "discovered_check":
        return f"{key}, a discovered check"
    if motif == "double_check":
        return f"{key}, a double check"
    if motif == "removal_of_defender" and len(targets) >= 2:
        return f"{key}, removing the defender of {targets[1]}"
    if motif == "trapped_piece" and targets:
        return f"{key}, trapping {targets[0]}"
    if motif in ("promotion", "underpromotion"):
        return f"{key}, promoting the pawn"
    return key


def _threat_desc(d: dict[str, Any], v: Voice, side: Color) -> str:
    if d.get("mate_in"):
        return f"mate, starting with {d['threat']}"
    motif = d.get("motif")
    md = d.get("motif_data")
    if motif in MOTIF_NAMES and md:
        return _tactic_phrase(motif, md, v)
    if d.get("attacks"):
        return f"{d['threat']}, attacking {v.pieces(d['attacks'][:3])}"
    threat_line = LineRef(**d["threat_line"]) if d.get("threat_line") else None
    takes, _ = captures(threat_line, side)
    if takes:
        return f"{d['threat']}, which wins {_count(takes)}"
    if d.get("target"):
        return f"{d['threat']}, winning {v.piece(d['target'])}"
    return f"{d['threat']}, winning material"


def _tactic(f: Fact, v: Voice, missed: bool) -> str:
    d = f.data
    key = d.get("key_move", "")
    targets = [v.piece(t) for t in d.get("targets", [])]
    piece = (d.get("piece") or {}).get("piece", "piece")
    motif = f.motif or ""
    prefix = f"{key} was" if missed else "It allows"
    after = f" after {d['prelude']}" if d.get("prelude") else ""
    if motif == "fork":
        if missed:
            return f"{key}{after} was a {piece} fork: it attacks {and_join(targets[:3])} at once."
        return f"It allows a {piece} fork{after}: {key} attacks {and_join(targets[:3])} at the same time."
    if motif == "pin":
        pinned = targets[0] if targets else "a piece"
        to = " to the king" if d.get("absolute") else (f" to {targets[1]}" if len(targets) > 1 else "")
        if d.get("use") == "pinned_defender":
            return f"{cap(pinned)} is pinned{to}, so it can't help after {key}."
        pinner = d.get("pinner")
        if pinner and pinner.get("square") != d.get("key_to"):
            by = f" by {v.piece(pinner)}"
            if missed:
                return f"{cap(pinned)} was pinned{to}{by}: {key} would have won it."
            return f"It leaves {pinned} pinned{to}{by}, and {key} wins it."
        return f"{prefix} {key}, pinning {pinned}{to}: it can't step away and is lost."
    if motif == "skewer" and len(targets) >= 2:
        return (
            f"{prefix} a skewer: {key} attacks {targets[0]}, and once it moves, {targets[1]} behind it falls."
        )
    if motif == "discovered_attack":
        hidden = v.piece(d.get("line_piece")) if d.get("line_piece") else "the piece behind it"
        target = targets[0] if targets else "material"
        return f"{prefix} a discovered attack: {key} unmasks {hidden} against {target}."
    if motif == "discovered_check":
        hidden = v.piece(d.get("line_piece")) if d.get("line_piece") else "the piece behind it"
        return (
            f"{prefix} a discovered check: {key} uncovers a check from {hidden}, "
            "and the moving piece is free to strike."
        )
    if motif == "double_check":
        return f"{prefix} a double check with {key}: only a king move helps, and material falls."
    if motif == "removal_of_defender" and len(targets) >= 2:
        return f"{prefix} {key}, removing the defender of {targets[1]}."
    if motif == "trapped_piece" and targets:
        return f"{cap(targets[0])} gets trapped: it has no safe square left."
    if motif in ("promotion", "underpromotion"):
        return f"{prefix} {key}: the pawn promotes."
    return f"{prefix} {key}."


def _how(how: str, d: dict[str, Any], v: Voice) -> str:
    target = v.piece(d.get("target")) if d.get("target") else "the threatened piece"
    return {
        "luft": "gives the king an escape square",
        "moves_away": f"moves {target} out of danger",
        "captures_attacker": "takes the attacking piece",
        "check": "gains time with a check",
        "blocks": "blocks the attack",
        "defends": f"defends {target}",
        "covers_square": "covers the square the threat needed",
    }.get(how, "deals with the threat")


_POSITIONAL: dict[str, Callable[[dict[str, Any]], str]] = {
    "king_safety": lambda d: (
        "It weakens your king: the pawn shield is thinner and lines toward the king open up."
    ),
    "isolated_pawn": lambda d: f"It leaves an isolated pawn on {and_join(d.get('squares', []))}.",
    "doubled_pawns": lambda d: f"It leaves doubled pawns on the {and_join(d.get('files', []))}-file.",
    "passed_pawn_allowed": lambda d: (
        f"It hands your opponent a passed pawn on {and_join(d.get('squares', []))}."
    ),
    "passed_pawn_missed": lambda d: (
        f"{d.get('best')} would have created a passed pawn on {and_join(d.get('squares', []))}."
    ),
    "castling_lost": lambda d: "Your king loses the right to castle and stays in the center.",
    "bishop_pair": lambda d: "It gives up the bishop pair.",
    "development": lambda d: f"Development falls behind: {d.get('count')} minor pieces are still at home.",
    "activity": lambda d: f"The pieces end up clearly less active than after {d.get('best')}.",
    "outpost_missed": lambda d: (
        f"{d.get('best')} would have put a piece on a strong outpost on {and_join(d.get('squares', []))}."
    ),
    "outpost_allowed": lambda d: f"Your opponent gets a strong outpost on {and_join(d.get('squares', []))}.",
    "open_file": lambda d: f"{d.get('best')} would have put a rook on an open file.",
}
_PRINCIPLES = {
    "early_queen": "The queen comes out early and can be chased around with tempo.",
    "same_piece_twice": "It moves the same piece twice while other pieces are still undeveloped.",
    "king_walk": "The king move gives up castling.",
    "weakening_pawn_move": "This pawn move weakens the squares around the king.",
}


def sentence(f: Fact, v: Voice, m: MoveReview, subject: str | None = None) -> str:
    """One sentence for a fact. `subject` replaces the better move's name ("It", "It also")
    when a section title already names it."""
    d = f.data
    best = subject or d.get("best", "")
    mover: Color = m.color
    line = line_text(f.line)
    if f.kind == "allows_mate":
        pattern = PATTERN_NAMES.get(d.get("pattern") or "")
        what = f"a {pattern}" if pattern else f"mate in {d['mate_in']}"
        return f"It allows {what}: {line}."
    if f.kind == "missed_mate":
        return f"{cap(v.who(mover))} had mate in {d['mate_in']}: {line}."
    if f.kind == "ignored_threat":
        opp: Color = other(mover)
        desc = _threat_desc(d, v, opp)
        if d.get("created_by"):
            first = f"{cap(v.whose(opp))} move {d['created_by']} threatened {desc}."
        else:
            first = f"{cap(v.who(opp))} {'were' if v.who(opp) == 'you' else 'was'} threatening {desc}."
        return f"{first} {m.san} doesn't deal with it: {line}{_dash(outcome(with_move(m, f.line), opp, v))}."
    if f.kind == "hangs_piece":
        victim = v.piece(d.get("victim"))
        if d.get("how") == "moved_into_attack":
            why = {
                "undefended": "nothing defends it",
                "cheaper_attacker": f"the {d.get('attacker')} that takes it is worth less",
            }.get(d.get("reason", ""), "it is attacked more times than it is defended")
            return f"{cap(victim)} can simply be taken: {d['capture']} — {why}."
        if d.get("how") == "removed_defender":
            return f"The {d.get('moved')} was guarding {victim}; once it moved, {d['capture']} wins it."
        return f"It leaves {victim} unprotected: {d['capture']}."
    if f.kind == "allows_tactic":
        lost = outcome(with_move(m, f.line), other(mover), v)
        return f"{_tactic(f, v, missed=False)} {cap(line)}{_dash(lost)}."
    if f.kind == "allows_attack":
        targets = d.get("targets", [])[:3]
        hits = f"attacks {v.pieces(targets)}" + (" at the same time" if len(targets) > 1 else "")
        lost = outcome(with_move(m, f.line), other(mover), v)
        return f"It allows {d['key_move']}, which {hits}: {line}{_dash(lost)}."
    if f.kind == "best_avoids":
        name = MOTIF_NAMES.get(f.motif or "", "tactic")
        return f"{best} avoids the {name}: {line}."
    if f.kind == "best_defends":
        return f"{best} would have protected {v.pieces(d.get('targets', [])[:3])}."
    if f.kind == "loses_material":
        lost = outcome(with_move(m, f.line), other(mover), v)
        return f"After {line}, {lost}." if lost else f"The strongest reply is {line}."
    if f.kind == "missed_tactic":
        return f"{_tactic(f, v, missed=True)} {cap(line)}{_dash(winnings(f.line, mover, v))}."
    if f.kind == "missed_material":
        victim = v.piece(d.get("victim"))
        state = "insufficiently defended" if d.get("defended") else "undefended"
        return f"{cap(victim)} was {state}: {d['capture']} would have won it."
    if f.kind == "missed_win":
        return f"{best} wins material by force: {line}{_dash(winnings(f.line, mover, v))}."
    if f.kind == "best_parries_threat":
        return f"{best} {_how(d['how'], d, v)}."
    if f.kind == "parries_threat":
        return f"It {_how(d['how'], d, v)}: {v.whose(other(mover))} threat {d['threat']} no longer works."
    if f.kind == "best_creates_threat":
        return f"{best} threatens {_threat_desc(d, v, mover)}."
    if f.kind == "executes_tactic":
        name = MOTIF_NAMES.get(f.motif or "", f.motif or "tactic")
        return f"A {name}: {line}{_dash(winnings(f.line, mover, v, would=False))}."
    if f.kind == "forces_mate":
        return f"It forces mate in {d['mate_in']}: {line}."
    if f.kind == "checkmate":
        pattern = PATTERN_NAMES.get(d.get("pattern") or "")
        return f"Checkmate{f' — a {pattern}' if pattern else ''}!"
    if f.kind == "sacrifice":
        return f"It offers the {d.get('piece')}, and the point is {line}."
    if f.kind == "only_move":
        second = (
            f"the next best, {d['second']}, was clearly worse" if d.get("second") else "nothing else held"
        )
        return f"It was the only good move here — {second}."
    if f.kind == "tablebase":
        best = f" {d['best']} was the way." if d.get("best") else ""
        return (
            f"With perfect play this endgame was a {d['before']}; after {m.san} it is a {d['after']}.{best}"
        )
    if f.kind == "stalemate":
        return "It's stalemate — a winning position turns into a draw."
    if f.kind == "positional":
        return _POSITIONAL.get(f.motif or "", lambda _: "The position becomes harder to play.")(d)
    if f.kind == "opening_principle":
        return _PRINCIPLES.get(f.motif or "", "")
    if f.kind == "clock":
        if f.motif == "rushed":
            return f"It was played in {d['spent']:.0f} seconds."
        return f"Only {d['remaining']:.0f} seconds were left on the clock."
    if f.kind == "book":
        return f"A known opening move ({d['eco']} {d['name']})."
    if f.kind == "forced":
        return "The only legal move."
    return ""


# --- headlines ------------------------------------------------------------------------------


def _headline(primary: Fact | None, m: MoveReview, v: Voice) -> str:
    if primary is None:
        if m.classification in ("best", "great", "brilliant"):
            return "The engine's top choice"
        if m.classification in ("excellent", "good"):
            return "A solid move"
        return "The engine prefers another move"
    d = primary.data
    k = primary.kind
    if k == "allows_mate":
        pattern = PATTERN_NAMES.get(d.get("pattern") or "")
        return f"Allows {('a ' + pattern) if pattern else 'mate in ' + str(d['mate_in'])}"
    if k == "missed_mate":
        return f"Misses mate in {d['mate_in']}"
    if k == "ignored_threat":
        return "Misses your opponent's threat" if v.user == m.color else "Misses the opponent's threat"
    if k == "hangs_piece":
        return f"Leaves {v.piece(d.get('victim'))} hanging"
    if k == "allows_tactic":
        return f"Allows a {MOTIF_NAMES.get(primary.motif or '', 'tactic')}"
    if k == "allows_attack":
        return (
            "Allows a double attack" if len(d.get("targets", [])) > 1 else "Allows an attack on a loose piece"
        )
    if k == "loses_material":
        return "Loses material"
    if k == "missed_tactic":
        return f"Misses a {MOTIF_NAMES.get(primary.motif or '', 'tactic')}"
    if k == "missed_material":
        return f"Misses {v.piece(d.get('victim'))}"
    if k == "missed_win":
        return "Misses a win of material"
    if k == "tablebase":
        return f"Turns a {d['before']} into a {d['after']}"
    if k == "stalemate":
        return "Stalemate throws away the win"
    if k == "positional":
        return {
            "king_safety": "Weakens the king",
            "isolated_pawn": "Creates an isolated pawn",
            "doubled_pawns": "Creates doubled pawns",
            "passed_pawn_allowed": "Gives the opponent a passed pawn",
            "castling_lost": "Gives up castling",
            "development": "Falls behind in development",
            "activity": "Makes the pieces passive",
            "outpost_allowed": "Gives the opponent an outpost",
        }.get(primary.motif or "", "A positional concession")
    if k == "opening_principle":
        return "Breaks an opening principle"
    if k == "checkmate":
        return "Checkmate"
    if k == "forces_mate":
        return f"Forces mate in {d['mate_in']}"
    if k == "executes_tactic":
        return f"Wins material with a {MOTIF_NAMES.get(primary.motif or '', 'tactic')}"
    if k == "sacrifice":
        return f"A sound {d.get('piece')} sacrifice"
    if k == "only_move":
        return "The only good move"
    if k == "parries_threat":
        return "Stops the threat"
    if k == "book":
        return d.get("name", "Opening theory")
    if k == "forced":
        return "Forced"
    return ""


def _lesson(primary: Fact | None) -> str | None:
    if primary is None:
        return None
    key = primary.motif
    if primary.kind == "hangs_piece":
        key = primary.data.get("how")
    elif primary.kind == "allows_mate":
        key = primary.data.get("pattern")
    return lesson_for(primary.kind, key)


def build_explanation(m: MoveReview, facts: list[Fact], user: Color | None) -> Explanation:
    explanation = _compose(m, facts, user)
    for section in explanation.sections:
        section.text = tidy(section.text)
    return explanation


def _compose(m: MoveReview, facts: list[Fact], user: Color | None) -> Explanation:
    v = Voice(user)
    by_kind = lambda kinds: [f for f in facts if f.kind in kinds]  # noqa: E731
    sections: list[ExplanationSection] = []
    annotations: list[Annotation] = []
    bad = m.classification in ("inaccuracy", "mistake", "miss", "blunder")
    best_san = m.best.san[0] if m.best and m.best.san else None
    best_label = f"{m.move_number}{'.' if m.color == 'white' else '...'}{best_san}" if best_san else None
    clock = by_kind(("clock",))

    if m.classification in ("book", "forced"):
        primary = facts[0] if facts else None
        text = (
            sentence(primary, v, m)
            if primary
            else ("The only legal move." if m.classification == "forced" else "Opening theory.")
        )
        return Explanation(
            headline=_headline(primary, m, v),
            sections=[
                ExplanationSection(title="Opening" if m.classification == "book" else "Forced", text=text)
            ],
        )

    if bad:
        wrong = by_kind(WRONG)[:2]
        better = by_kind(BETTER)[:2]
        primary = wrong[0] if wrong else (better[0] if better else None)
        if wrong:
            text = " ".join(sentence(f, v, m) for f in wrong + clock)
            sections.append(
                ExplanationSection(
                    title="What went wrong", text=text, fact_ids=[f.id for f in wrong], line=wrong[0].line
                )
            )
        if better:
            title = f"Better was {best_label}" if best_label else "What was better"
            sections.append(
                ExplanationSection(
                    title=title,
                    text=" ".join(
                        sentence(f, v, m, subject="It" if i == 0 else "It also") for i, f in enumerate(better)
                    ),
                    fact_ids=[f.id for f in better],
                    line=better[0].line or _best_line(m),
                )
            )
        if not sections:
            sections.append(_fallback(m, v, best_label))
        elif not better and best_label:
            sections.append(
                ExplanationSection(
                    title=f"Better was {best_label}", text=_keeps(m, v, best_label), line=_best_line(m)
                )
            )
        for f in wrong[:1] + better[:1]:
            annotations += f.annotations
        hints, focus = _hints(m, facts)
        return Explanation(
            headline=_headline(primary, m, v),
            sections=sections,
            lesson=_lesson(primary),
            annotations=annotations,
            hints=hints,
            focus=focus,
        )

    good = by_kind(GOOD)[:2]
    primary = good[0] if good else None
    if good:
        sections.append(
            ExplanationSection(
                title="Why it works",
                text=" ".join(sentence(f, v, m) for f in good),
                fact_ids=[f.id for f in good],
                line=good[0].line,
            )
        )
        annotations += good[0].annotations
    elif m.classification in ("best", "great", "brilliant", "excellent"):
        sections.append(ExplanationSection(title="The idea", text=_keeps(m, v, None)))
    if m.classification in ("excellent", "good") and best_label:
        better = by_kind((*BETTER, "positional"))[:1]
        text = sentence(better[0], v, m) if better else _keeps(m, v, best_label)
        sections.append(
            ExplanationSection(
                title=f"Even stronger was {best_label}",
                text=text,
                line=better[0].line if better and better[0].line else _best_line(m),
            )
        )
    return Explanation(
        headline=_headline(primary, m, v), sections=sections, lesson=None, annotations=annotations
    )


_THEME_HINTS = {
    "fork": "One of your pieces can attack two targets at once.",
    "pin": "Look for a piece of theirs that can't move without exposing something bigger behind it.",
    "skewer": "Attack their most valuable piece along a line: when it moves, what's behind it falls.",
    "discovered_attack": "Moving one piece can uncover an attack by the piece behind it.",
    "discovered_check": "Moving one piece can uncover a check by the piece behind it.",
    "double_check": "There's a way to give check with two pieces at once.",
    "removal_of_defender": "One of their pieces is the only guard of another. Take the guard away.",
    "trapped_piece": "One of their pieces has run out of safe squares.",
    "promotion": "A pawn is close to promoting.",
}


def _hints(m: MoveReview, facts: list[Fact]) -> tuple[list[str], str | None]:
    """Nudges toward the better move, from general to specific, never naming the move itself."""
    kinds = {f.kind: f for f in facts}
    hints: list[str] = []
    if "missed_mate" in kinds:
        hints.append(
            f"There is a forced mate in {kinds['missed_mate'].data.get('mate_in')}. Look at every check."
        )
    elif "missed_tactic" in kinds:
        motif = kinds["missed_tactic"].motif or ""
        hints.append(
            _THEME_HINTS.get(motif, "There's a tactic that wins material. Try the forcing moves first.")
        )
    elif "missed_material" in kinds:
        hints.append("Something of your opponent's can be won right now. Check what is undefended.")
    elif "ignored_threat" in kinds or "best_parries_threat" in kinds:
        hints.append("Your opponent is threatening something. What does their last move attack?")
    elif "allows_mate" in kinds:
        hints.append("Careful: the obvious moves let your opponent mate. Look at their checks first.")
    elif "best_avoids" in kinds:
        name = MOTIF_NAMES.get(kinds["best_avoids"].motif or "", "tactic")
        hints.append(f"Your move allowed a {name}. Find a move that keeps everything protected.")
    elif "allows_attack" in kinds or "best_defends" in kinds or "hangs_piece" in kinds:
        hints.append("Something of yours is about to be attacked. Find a move that keeps it safe.")
    else:
        hints.append("Start with checks, captures and threats, for both sides.")
    focus = None
    if m.best and m.best.uci:
        board = chess.Board(m.fen_before)
        move = chess.Move.from_uci(m.best.uci[0])
        piece = board.piece_at(move.from_square)
        if piece is not None:
            focus = chess.square_name(move.from_square)
            hints.append(f"Look at your {piece_name(piece.piece_type)} on {focus}.")
    return hints, focus


def _best_line(m: MoveReview) -> LineRef | None:
    if not m.best or not m.best.uci:
        return None
    return LineRef(start_fen=m.fen_before, uci=m.best.uci[:MAX_LINE], san=m.best.san[:MAX_LINE])


def eval_words(score: Score, color: Color, v: Voice) -> str:
    """'you are clearly better', 'Black is winning', 'it's about equal' — for `color`."""
    if score.result is not None:
        return "the game is over"
    if score.mate is not None:
        mating: Color = "white" if score.mate > 0 else "black"
        return f"{v.who(mating)} {'have' if v.who(mating) == 'you' else 'has'} a forced mate"
    cp = score.cp or 0
    ahead: Color = "white" if cp > 0 else "black"
    size = abs(cp)
    if size < 50:
        return "it's about equal"
    word = (
        "slightly better"
        if size < 120
        else "clearly better"
        if size < 300
        else "winning"
        if size < 700
        else "completely winning"
    )
    subject = v.who(ahead)
    return f"{subject} {'are' if subject == 'you' else 'is'} {word}"


def _keeps(m: MoveReview, v: Voice, best_label: str | None) -> str:
    """What the position looks like with best play, in words."""
    if best_label is None:
        return f"After {m.san}, {eval_words(m.eval_after, m.color, v)}."
    return f"After {best_label}, {eval_words(m.eval_before, m.color, v)}: {line_text(_best_line(m), 6)}."


def _fallback(m: MoveReview, v: Voice, best_label: str | None) -> ExplanationSection:
    """No clean tactical or positional story: say what the engine shows, honestly."""
    reply = ""
    if m.refutation and m.refutation.san:
        refutation = LineRef(start_fen=m.fen_after, uci=m.refutation.uci, san=m.refutation.san)
        reply = f" After {m.san}, the strongest reply is {line_text(refutation, 6)}."
    best = f" The engine prefers {best_label}." if best_label else ""
    return ExplanationSection(
        title="What the engine sees",
        text=f"There's no single tactic here — it's a matter of accuracy.{best}{reply}",
        line=_best_line(m),
    )
