"""The "why" of one move: verified facts built from engine lines and the analyzers.

Every fact here is backed by a concrete line: we only say a move "allows a fork" when the
engine's refutation actually wins one of the forked pieces, and we only say a threat was
ignored when the opponent's best reply carries it out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import chess

from chess_analysis_engine.engine.pool import EnginePool
from chess_analysis_engine.engine.scoring import missed_mate as loses_mate
from chess_analysis_engine.facts import endgame
from chess_analysis_engine.facts.board import (
    VALUES,
    best_capture,
    captured_value,
    piece_name,
    sacrificed_material,
    see,
)
from chess_analysis_engine.facts.clock import clock_notes
from chess_analysis_engine.facts.lines import Line, prepend
from chess_analysis_engine.facts.mates import mate_pattern
from chess_analysis_engine.facts.positional import compare, opening_principles
from chess_analysis_engine.facts.tactics import Motif, detect_motifs
from chess_analysis_engine.facts.threats import Threat, find_threat, newly_winnable, parry_method, same_threat
from chess_analysis_engine.models import (
    Annotation,
    Classification,
    ClockInfo,
    Difficulty,
    Fact,
    OpeningRef,
    Phase,
    PositionEval,
    color_name,
)
from chess_analysis_engine.storage.db import Database

BAD = {"inaccuracy", "mistake", "miss", "blunder"}
# Detectors that disagree too often with lichess's tags to be named in an explanation; their
# lines are still described concretely ("after X, Y you lose the rook").
LOW_CONFIDENCE = {"deflection", "attraction", "zwischenzug", "quiet_move", "sacrifice", "perpetual_check"}
MIN_MATERIAL = 100
POSITIONAL_PLIES = 6


@dataclass
class MoveInput:
    board: chess.Board  # position before the move, with game history
    move: chess.Move
    before: PositionEval
    after: PositionEval
    classification: Classification
    ep_loss: float = 0.0
    clock: ClockInfo | None = None
    base_seconds: float | None = None
    phase: Phase = "middlegame"
    opening: OpeningRef | None = None


@dataclass
class MoveFacts:
    facts: list[Fact] = field(default_factory=list)
    difficulty: Difficulty | None = None


def label(board: chess.Board, move: chess.Move) -> str:
    """'14. Bd3' / '14...Qxb2' for a move played from `board`."""
    san = board.san(move)
    number = board.fullmove_number
    return f"{number}. {san}" if board.turn == chess.WHITE else f"{number}...{san}"


def line_label(line: Line, ply: int) -> str:
    return label(line.boards[ply], line.moves[ply])


def numbered(line: Line, start: int, stop: int) -> str:
    """'8. Qxd8+ Kxd8' for plies [start, stop) of a line ('' when empty)."""
    parts: list[str] = []
    for k in range(start, stop):
        board = line.boards[k]
        san = line.sans[k]
        if board.turn == chess.WHITE:
            parts.append(f"{board.fullmove_number}. {san}")
        else:
            parts.append(f"{board.fullmove_number}...{san}" if k == start else san)
    return " ".join(parts)


def piece_at(board: chess.Board, square: chess.Square) -> dict[str, str] | None:
    piece = board.piece_at(square)
    if piece is None:
        return None
    return {
        "piece": piece_name(piece.piece_type),
        "square": chess.square_name(square),
        "color": color_name(piece.color),
    }


class _Facts:
    def __init__(self) -> None:
        self.items: list[Fact] = []

    def add(self, kind: str, importance: float, **fields: Any) -> Fact:
        fact = Fact(id=f"f{len(self.items) + 1}", kind=kind, importance=importance, **fields)
        self.items.append(fact)
        return fact

    def has(self, *kinds: str) -> bool:
        return any(f.kind in kinds for f in self.items)


def _arrow(move: chess.Move, brush: str) -> Annotation:
    return Annotation(
        orig=chess.square_name(move.from_square), dest=chess.square_name(move.to_square), brush=brush
    )  # type: ignore[arg-type]


def _circle(square: chess.Square, brush: str) -> Annotation:
    return Annotation(orig=chess.square_name(square), brush=brush)  # type: ignore[arg-type]


def _motif_data(line: Line, motif: Motif, first_ply: int = 0) -> dict[str, Any]:
    """Squares and pieces involved in a motif, described in the position after its key move.

    `prelude` holds the moves from `first_ply` up to the key move ("after 8. Qxd8+ Kxd8, ...").
    """
    after = line.boards[motif.ply + 1]
    before = line.boards[motif.ply]
    data: dict[str, Any] = {
        "key_move": line_label(line, motif.ply),
        "key_to": chess.square_name(line.moves[motif.ply].to_square),
        "prelude": numbered(line, first_ply, motif.ply),
        "piece": piece_at(after, line.moves[motif.ply].to_square),
        "targets": [p for t in motif.targets if (p := piece_at(after, t) or piece_at(before, t))],
    }
    if motif.square is not None and motif.square != line.moves[motif.ply].to_square:
        data["line_piece"] = piece_at(after, motif.square)
    if motif.name == "pin" and motif.square is not None:
        data["pinner"] = piece_at(after, motif.square)
    for key in ("absolute", "use", "royal", "pattern", "mate_in"):
        if key in motif.detail:
            data[key] = motif.detail[key]
    if "pinned" in motif.detail:
        data["pinned"] = piece_name(motif.detail["pinned"])
    if motif.detail.get("moved"):
        data["moved"] = piece_name(motif.detail["moved"])
    return data


def _motif_annotations(line: Line, motif: Motif, brush: str) -> list[Annotation]:
    shapes = [_arrow(line.moves[motif.ply], brush)]
    shapes += [_circle(t, brush) for t in motif.targets[:3]]
    return shapes


def _confident(motifs: list[Motif], actor_first_ply: int) -> Motif | None:
    """The leading motif worth naming: confident, and starting with the actor's first moves."""
    for motif in motifs:
        if motif.name in LOW_CONFIDENCE or motif.name == "mate":
            continue
        if motif.ply <= actor_first_ply + 2:
            return motif
    return None


def _hanging(board: chess.Board, move: chess.Move, reply: chess.Move) -> dict[str, Any] | None:
    """If the opponent's first reply simply wins a piece, which one and why it was loose."""
    after = board.copy(stack=False)
    after.push(move)
    if not after.is_capture(reply):
        return None
    gain = see(after, reply)
    if reply.to_square == move.to_square:
        gain -= captured_value(board, move)  # taking back after our capture is just a trade
    if gain < MIN_MATERIAL:
        return None
    square = reply.to_square
    victim = after.piece_at(square)
    if victim is None:
        return None
    mover = board.turn
    if square == move.to_square:
        how = "moved_into_attack"
    elif move.from_square in board.attackers(mover, square) and square not in after.attacks(move.to_square):
        how = "removed_defender"
    else:
        how = "left_unprotected"
    attacker = after.piece_type_at(reply.from_square) or chess.PAWN
    defended = bool(after.attackers(mover, square))
    if not defended:
        reason = "undefended"
    elif VALUES[attacker] < VALUES[victim.piece_type]:
        reason = "cheaper_attacker"
    else:
        reason = "outnumbered"
    return {
        "victim": piece_at(after, square),
        "how": how,
        "reason": reason,
        "capture": label(after, reply),
        "attacker": piece_name(attacker),
        "defended": defended,
        "moved": piece_name(board.piece_type_at(move.from_square) or chess.PAWN),
        "gain": gain,
    }


def _caused_by(feature: str, board: chess.Board, move: chess.Move, phase: Phase) -> bool:
    """Is it fair to blame this positional change on the move itself?"""
    piece = board.piece_type_at(move.from_square)
    king = board.king(board.turn)
    if feature == "king_safety":
        # A pawn shield only exists once the king has castled (or tucked itself away) on a wing.
        if king is None or chess.square_file(king) in (3, 4):
            return False
        near_king = abs(chess.square_file(move.from_square) - chess.square_file(king)) <= 1
        return piece == chess.KING or (piece == chess.PAWN and near_king)
    if feature == "castling_lost":
        return piece in (chess.KING, chess.ROOK) and not board.is_castling(move)
    if feature == "development":
        return phase == "opening"
    return feature not in ("activity", "open_file")


def _defended_by(
    board: chess.Board, best: chess.Move, reply: chess.Move, targets: list[chess.Square]
) -> list[chess.Square]:
    """Targets of the opponent's reply that would have been safe after the better move."""
    after_best = board.copy(stack=False)
    after_best.push(best)
    if not after_best.is_legal(reply):
        return []
    after_best.push(reply)
    probe = after_best.copy(stack=False)
    probe.turn = not board.turn
    probe.ep_square = None
    mover = board.turn
    return [t for t in targets if after_best.color_at(t) == mover and best_capture(probe, t)[0] <= 0]


def _mate_for(score_mate: int | None, color: chess.Color) -> int | None:
    if score_mate is None:
        return None
    if (score_mate > 0) == (color == chess.WHITE):
        return abs(score_mate)
    return None


def _difficulty(board: chess.Board, before: PositionEval, best_line: Line | None) -> Difficulty | None:
    """How hard the best move was to find: forcing and quick → easy; quiet, slow or a sacrifice → hard."""
    if best_line is None or not best_line.moves:
        return None
    best = best_line.moves[0]
    mover = board.turn
    forcing = board.is_capture(best) or board.gives_check(best)
    payoff = best_line.settle_point(mover)
    sacrifice = sacrificed_material(board, best) >= 200
    stable = _stable_depth(before.best_by_depth, best.uci())
    if forcing and payoff <= 3 and not sacrifice and stable <= 10:
        return "easy"
    if sacrifice or (not forcing and payoff >= 5) or stable >= 16:
        return "hard"
    return "medium"


def _stable_depth(best_by_depth: list[tuple[int, str]], best_uci: str) -> int:
    """First search depth from which the engine kept `best_uci` as its choice."""
    depth = best_by_depth[-1][0] if best_by_depth else 0
    for d, move in reversed(best_by_depth):
        if move != best_uci:
            break
        depth = d
    return depth


def _position_key(board: chess.Board) -> tuple[str, chess.Color, chess.Bitboard, chess.Square | None]:
    """What makes two positions "the same" for the repetition rule."""
    ep = board.ep_square if board.has_legal_en_passant() else None
    return board.board_fen(), board.turn, board.clean_castling_rights(), ep


def _earlier_occurrences(board: chess.Board) -> list[str]:
    """The earlier moves that reached `board`'s position, e.g. ['49. Kf1', '51. Kf1']."""
    target = _position_key(board)
    replay = board.root()
    found: list[str] = []
    for move in board.move_stack[:-1]:
        name = label(replay, move)
        replay.push(move)
        if _position_key(replay) == target:
            found.append(name)
    return found


def explain_move(
    inp: MoveInput,
    pool: EnginePool | None = None,
    db: Database | None = None,
    use_threats: bool = True,
    use_tablebase: bool = True,
) -> MoveFacts:
    board, move = inp.board, inp.move
    mover, opponent = board.turn, not board.turn
    out = _Facts()

    if inp.classification == "book":
        if inp.opening:
            out.add("book", 10, data={"eco": inp.opening.eco, "name": inp.opening.name})
        return MoveFacts(out.items)
    if inp.classification == "forced":
        out.add("forced", 10)
        return MoveFacts(out.items)

    best_uci = inp.before.best.uci if inp.before.best else []
    best_move = chess.Move.from_uci(best_uci[0]) if best_uci else None
    is_best = best_move == move
    bad = inp.classification in BAD
    after = board.copy(stack=False)
    after.push(move)
    reply_uci = inp.after.best.uci if inp.after.best else []
    played_line = prepend(board, move, reply_uci)  # ply 0: our move, then the opponent's best line
    refutation = Line.from_uci(after, reply_uci)
    best_line = None if is_best or not best_uci else Line.from_uci(board, best_uci)
    best_label = label(board, best_move) if best_move is not None else None

    # --- mates --------------------------------------------------------------------------
    mate_against = _mate_for(inp.after.score.mate, opponent)
    if after.is_checkmate():
        mate_against = None
    if bad and mate_against is not None and refutation.moves:
        shown = refutation.trimmed(opponent, max_plies=2 * mate_against)
        out.add(
            "allows_mate",
            100,
            actor=color_name(opponent),
            line=shown.ref(),
            data={
                "mate_in": mate_against,
                "pattern": mate_pattern(shown.end),
                "first": line_label(refutation, 0),
            },
            annotations=[_arrow(refutation.moves[0], "red")],
        )
    missed_mate = _mate_for(inp.before.score.mate, mover)
    # Same rule as the "Miss" label: the mate is gone, or a short one (mate in 3 or less) got longer.
    if (
        best_line is not None
        and missed_mate is not None
        and loses_mate(color_name(mover), inp.before.score, inp.after.score)
    ):
        shown = best_line.trimmed(mover, max_plies=2 * missed_mate)
        out.add(
            "missed_mate",
            95,
            actor=color_name(mover),
            line=shown.ref(),
            data={"mate_in": missed_mate, "pattern": mate_pattern(shown.end), "first": best_label},
            annotations=[_arrow(best_line.moves[0], "green")],
        )

    # --- the opponent's threat before the move ------------------------------------------
    threat: Threat | None = None
    if pool is not None and use_threats:
        threat = find_threat(pool, board)
    executed = False
    if threat is not None:
        opponent_gain = played_line.net_material(opponent, played_line.settle_point(opponent))
        executed = same_threat(threat, after, reply_uci) and (opponent_gain > 0 or mate_against is not None)
        threat_data = _threat_data(board, threat)
        if bad and executed:
            out.add(
                "ignored_threat",
                90,
                actor=color_name(opponent),
                motif=threat.main_motif.name if threat.main_motif else None,
                line=Line(after, played_line.trimmed(opponent).moves[1:]).ref(),
                data=threat_data,
                annotations=[_arrow(threat.move, "red")]
                + ([_circle(threat.target, "red")] if threat.target is not None else []),
            )
            if best_move is not None and not is_best:
                how = parry_method(board, best_move, threat)
                if how:
                    out.add(
                        "best_parries_threat",
                        45,
                        actor=color_name(mover),
                        data={**threat_data, "how": how, "best": best_label},
                        annotations=[_arrow(best_move, "green")],
                    )
        elif not bad and not executed:
            how = parry_method(board, move, threat)
            if how:
                out.add(
                    "parries_threat",
                    40,
                    actor=color_name(mover),
                    data={**threat_data, "how": how, "move": label(board, move)},
                    annotations=[_arrow(move, "green")],
                )

    # --- what the refutation wins -------------------------------------------------------
    if bad and mate_against is None and refutation.moves:
        settle = played_line.settle_point(opponent)
        gain = played_line.net_material(opponent, settle)
        hang = _hanging(board, move, refutation.moves[0])
        # Trim the line that starts with our move (so trades it starts are counted), then show
        # only the opponent's part.
        shown = Line(after, played_line.trimmed(opponent).moves[1:])
        covered = out.has("ignored_threat")  # the threat already tells this story
        if hang is not None and gain >= MIN_MATERIAL and not covered:
            victim_square = refutation.moves[0].to_square
            out.add(
                "hangs_piece",
                80,
                actor=color_name(opponent),
                line=shown.ref(),
                material=gain,
                data=hang,
                annotations=[_arrow(refutation.moves[0], "red"), _circle(victim_square, "red")],
            )
        motif = _confident(detect_motifs(played_line, opponent), actor_first_ply=1)
        if motif is not None and motif.name != "hanging_piece" and gain > 0 and not covered:
            out.add(
                "allows_tactic",
                78,
                actor=color_name(opponent),
                motif=motif.name,
                line=shown.ref(),
                material=gain,
                data=_motif_data(played_line, motif, first_ply=1),
                annotations=_motif_annotations(played_line, motif, "red"),
            )
            # Does the better move sidestep it? (The engine's line after it never allows the key move.)
            if best_line is not None and best_line.moves:
                key = played_line.moves[motif.ply]
                if key not in best_line.moves[1:7:2]:
                    out.add(
                        "best_avoids",
                        47,
                        actor=color_name(mover),
                        motif=motif.name,
                        line=best_line.trimmed(mover).ref(),
                        data={"best": best_label, "key_move": line_label(played_line, motif.ply)},
                        annotations=[_arrow(best_line.moves[0], "green")],
                    )
        # The opponent's key reply: which of our pieces it suddenly makes winnable.
        first_reply = refutation.moves[0]
        targets = [] if after.is_capture(first_reply) else newly_winnable(after, first_reply)
        if targets and gain >= MIN_MATERIAL and not covered and not out.has("hangs_piece", "allows_tactic"):
            out.add(
                "allows_attack",
                72,
                actor=color_name(opponent),
                line=shown.ref(),
                material=gain,
                data={
                    "key_move": line_label(refutation, 0),
                    "piece": piece_at(refutation.boards[1], first_reply.to_square),
                    "targets": [p for t in targets if (p := piece_at(after, t))],
                },
                annotations=[_arrow(first_reply, "red")] + [_circle(t, "red") for t in targets[:3]],
            )
            if best_move is not None and not is_best:
                defended = _defended_by(board, best_move, first_reply, targets)
                if defended:
                    out.add(
                        "best_defends",
                        44,
                        actor=color_name(mover),
                        data={
                            "best": best_label,
                            "targets": [p for t in defended if (p := piece_at(board, t))],
                        },
                        annotations=[_arrow(best_move, "green")]
                        + [_circle(t, "green") for t in defended[:3]],
                    )
        if gain >= MIN_MATERIAL and not out.has(
            "hangs_piece", "allows_tactic", "ignored_threat", "allows_attack"
        ):
            out.add(
                "loses_material",
                60,
                actor=color_name(opponent),
                line=shown.ref(),
                material=gain,
                data={"gain": gain},
                annotations=[_arrow(refutation.moves[0], "red")],
            )

    # --- what the best move would have won ----------------------------------------------
    if best_line is not None and best_line.moves and missed_mate is None:
        best_settle = best_line.settle_point(mover)
        best_gain = best_line.net_material(mover, best_settle)
        played_gain = played_line.net_material(mover, played_line.settle_point(mover))
        # Only a real win counts: the better move must gain material, not just lose less.
        if best_gain >= MIN_MATERIAL and best_gain - played_gain >= MIN_MATERIAL:
            shown = best_line.trimmed(mover)
            motif = _confident(detect_motifs(best_line, mover), actor_first_ply=0)
            first = best_line.moves[0]
            if motif is not None and motif.name != "hanging_piece":
                out.add(
                    "missed_tactic",
                    70,
                    actor=color_name(mover),
                    motif=motif.name,
                    line=shown.ref(),
                    material=best_gain,
                    data=_motif_data(best_line, motif),
                    annotations=_motif_annotations(best_line, motif, "green"),
                )
            elif board.is_capture(first) and see(board, first) > 0:
                victim_type = (
                    chess.PAWN if board.is_en_passant(first) else board.piece_type_at(first.to_square)
                )
                out.add(
                    "missed_material",
                    68,
                    actor=color_name(mover),
                    line=shown.ref(),
                    material=best_gain,
                    data={
                        "capture": best_label,
                        "victim": piece_at(board, first.to_square)
                        or {
                            "piece": piece_name(victim_type or chess.PAWN),
                            "square": chess.square_name(first.to_square),
                        },
                        "defended": bool(board.attackers(opponent, first.to_square)),
                        "gain": best_gain,
                    },
                    annotations=[_arrow(first, "green"), _circle(first.to_square, "green")],
                )
            else:
                out.add(
                    "missed_win",
                    62,
                    actor=color_name(mover),
                    line=shown.ref(),
                    material=best_gain,
                    data={"best": best_label, "gain": best_gain},
                    annotations=[_arrow(first, "green")],
                )

    # --- what the played move itself achieves (good moves) -------------------------------
    if not bad:
        own = _confident(detect_motifs(played_line, mover), actor_first_ply=0)
        own_gain = played_line.net_material(mover, played_line.settle_point(mover))
        if own is not None and own.ply == 0 and own_gain > 0:
            out.add(
                "executes_tactic",
                55,
                actor=color_name(mover),
                motif=own.name,
                line=played_line.trimmed(mover).ref(),
                material=own_gain,
                data=_motif_data(played_line, own),
                annotations=_motif_annotations(played_line, own, "green"),
            )
        own_mate = _mate_for(inp.after.score.mate, mover)
        if own_mate is not None and not after.is_checkmate():
            out.add(
                "forces_mate",
                60,
                actor=color_name(mover),
                line=played_line.trimmed(mover, max_plies=2 * own_mate + 1).ref(),
                data={"mate_in": own_mate},
            )
        if after.is_checkmate():
            out.add("checkmate", 60, actor=color_name(mover), data={"pattern": mate_pattern(after)})
        if inp.classification == "brilliant":
            offered = sacrificed_material(board, move)
            out.add(
                "sacrifice",
                58,
                actor=color_name(mover),
                material=offered,
                data={
                    "offered": offered,
                    "move": label(board, move),
                    "piece": piece_name(board.piece_type_at(move.from_square) or chess.PAWN),
                },
                line=played_line.trimmed(mover).ref(),
                annotations=[_arrow(move, "green")],
            )
        if inp.classification == "great" and len(inp.before.lines) > 1:
            second = inp.before.lines[1]
            out.add(
                "only_move",
                50,
                actor=color_name(mover),
                data={"second": label(board, chess.Move.from_uci(second.uci[0])) if second.uci else None},
            )

    # --- what the best move threatens (when you missed it) ------------------------------
    if bad and best_move is not None and not is_best and pool is not None and use_threats:
        after_best = board.copy(stack=False)
        after_best.push(best_move)
        idea = find_threat(pool, after_best)
        if idea is not None and idea.side == mover:
            out.add(
                "best_creates_threat",
                42,
                actor=color_name(mover),
                motif=idea.main_motif.name if idea.main_motif else None,
                data={**_threat_data(after_best, idea), "best": best_label},
                annotations=[_arrow(best_move, "green")],
            )

    # --- endgames ---------------------------------------------------------------------
    if bad and use_tablebase and endgame.in_range(board):
        change = endgame.result_change(board, after, db)
        if change is not None:
            out.add(
                "tablebase",
                88,
                actor=color_name(mover),
                data={"before": change[0], "after": change[1], "best": best_label},
            )
    if after.is_stalemate() and inp.ep_loss > 0.2:
        out.add("stalemate", 92, actor=color_name(mover))

    # --- repetition: online games end on the third one ------------------------------------
    history = board.copy()
    history.push(move)
    if history.is_repetition(3):
        out.add(
            "repetition",
            91 if bad else 52,
            actor=color_name(mover),
            data={"move": label(board, move), "earlier": _earlier_occurrences(history)},
        )
    elif bad and refutation.moves:
        reply = refutation.moves[0]
        history.push(reply)
        if history.is_repetition(3):
            out.add(
                "allows_repetition",
                91,
                actor=color_name(opponent),
                data={"reply": line_label(refutation, 0), "earlier": _earlier_occurrences(history)},
                annotations=[_arrow(reply, "red")],
            )

    # --- positional reasons, when nothing tactical explains the loss ---------------------
    tactical = out.has(
        "allows_mate",
        "missed_mate",
        "ignored_threat",
        "hangs_piece",
        "allows_tactic",
        "missed_tactic",
        "missed_material",
        "loses_material",
        "tablebase",
        "stalemate",
        "repetition",
        "allows_repetition",
        "missed_win",
    )
    if (bad or inp.classification in ("good", "excellent")) and best_line is not None and not tactical:
        # Compare right after the move and the reply, so only what the move itself causes counts.
        played_end = played_line.boards[min(len(played_line), 2)]
        best_end = best_line.boards[min(len(best_line), 2)]
        for diff in [
            d for d in compare(best_end, played_end, mover) if _caused_by(d.feature, board, move, inp.phase)
        ][:2]:
            out.add(
                "positional",
                30 + 5 * diff.weight,
                actor=color_name(mover),
                motif=diff.feature,
                data={**diff.detail, "best": best_label},
            )
        if bad and inp.phase == "opening":
            for principle in opening_principles(board, move):
                out.add(
                    "opening_principle",
                    32,
                    actor=color_name(mover),
                    motif=principle,
                    data={"move": label(board, move)},
                )

    # --- the clock ------------------------------------------------------------------------
    if bad:
        for kind, data in clock_notes(inp.clock, inp.base_seconds):
            out.add("clock", 20, actor=color_name(mover), motif=kind, data=data)

    facts = sorted(out.items, key=lambda f: -f.importance)
    return MoveFacts(facts, _difficulty(board, inp.before, best_line) if not is_best else None)


def _threat_data(board: chess.Board, threat: Threat) -> dict[str, Any]:
    """What the threat is, described from the board where the threatening side moves twice."""
    start = threat.line.start
    data: dict[str, Any] = {
        "threat": label(start, threat.move),
        "gain": threat.gain,
        "mate_in": threat.mate_in,
        "motif": threat.main_motif.name if threat.main_motif else None,
    }
    if threat.target is not None:
        data["target"] = piece_at(start, threat.target)
    if threat.main_motif is not None and threat.main_motif.name not in LOW_CONFIDENCE | {"mate"}:
        data["motif_data"] = _motif_data(threat.line, threat.main_motif)
    if board.move_stack:
        last = board.peek()
        created = threat.move.from_square == last.to_square or (
            last.from_square in chess.SquareSet(chess.between(threat.move.from_square, threat.move.to_square))
        )
        if created:
            previous = board.copy()
            previous.pop()
            data["created_by"] = label(previous, last)
    if not start.is_capture(threat.move):
        data["attacks"] = [p for t in newly_winnable(start, threat.move) if (p := piece_at(start, t))]
    data["threat_line"] = threat.line.ref().model_dump()
    data["captured_value"] = captured_value(start, threat.move) if start.is_capture(threat.move) else 0
    data["value"] = VALUES.get(start.piece_type_at(threat.move.from_square) or chess.PAWN, 0)
    return data
