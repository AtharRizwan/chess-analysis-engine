"""Tactical motif detectors.

Each detector reads a line from the point of view of the side carrying out the idea (the
"actor") and only reports a motif when the line shows it paying off: material actually won,
or mate. We never call something a fork unless the engine's own line wins a forked piece.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import chess

from chess_analysis_engine.facts.board import (
    VALUES,
    best_capture,
    captured_value,
    captures_on,
    sacrificed_material,
    see,
)
from chess_analysis_engine.facts.lines import Line
from chess_analysis_engine.facts.mates import mate_pattern

SLIDERS = (chess.BISHOP, chess.ROOK, chess.QUEEN)
_ROOK_DIRS = ((0, 1), (0, -1), (1, 0), (-1, 0))
_BISHOP_DIRS = ((1, 1), (1, -1), (-1, 1), (-1, -1))

# When several motifs start on the same move, the more specific one leads the explanation.
PRIORITY = [
    "mate",
    "double_check",
    "discovered_check",
    "discovered_attack",
    "fork",
    "skewer",
    "pin",
    "removal_of_defender",
    "deflection",
    "attraction",
    "trapped_piece",
    "zwischenzug",
    "promotion",
    "underpromotion",
    "hanging_piece",
    "sacrifice",
    "quiet_move",
    "perpetual_check",
]


@dataclass
class Motif:
    name: str
    ply: int  # index of the key move in the line
    square: chess.Square | None  # where the key piece stands after the key move
    targets: list[chess.Square] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Ctx:
    line: Line
    actor: chess.Color
    settle: int

    @property
    def enemy(self) -> chess.Color:
        return not self.actor

    def actor_plies(self, stop: int | None = None) -> Iterator[int]:
        stop = self.settle if stop is None else stop
        for k in range(min(stop, len(self.line))):
            if self.line.mover(k) == self.actor:
                yield k

    def gain(self, k: int) -> int:
        """Material the actor nets from before move `k` to the settle point."""
        return self.line.balance(self.settle, self.actor) - self.line.balance(k, self.actor)

    def mates(self) -> bool:
        end = self.line.boards[self.settle]
        return end.is_checkmate() and end.turn != self.actor

    def pays_off(self, k: int) -> bool:
        return self.mates() or self.gain(k) > 0

    def first_capture_on(self, start: int, squares: set[chess.Square]) -> int | None:
        for k in range(start, min(self.settle, len(self.line))):
            move = self.line.moves[k]
            board = self.line.boards[k]
            if board.turn == self.actor and board.is_capture(move) and move.to_square in squares:
                return k
        return None

    def first_capture_of(self, start: int, squares: set[chess.Square]) -> int | None:
        """Like first_capture_on, but follows the pieces on `squares` when they move."""
        tracked = set(squares)
        for k in range(start, min(self.settle, len(self.line))):
            move = self.line.moves[k]
            board = self.line.boards[k]
            if board.turn == self.actor:
                if board.is_capture(move) and move.to_square in tracked:
                    return k
            elif move.from_square in tracked:
                tracked.discard(move.from_square)
                tracked.add(move.to_square)
        return None

    def previous(self, k: int) -> tuple[chess.Board, chess.Move] | None:
        """The move played just before ply `k` (possibly before the line started) and its board."""
        if k > 0:
            return self.line.boards[k - 1], self.line.moves[k - 1]
        if self.line.start.move_stack:
            board = self.line.start.copy()
            move = board.pop()
            return board, move
        return None


def _directions(piece_type: chess.PieceType) -> tuple[tuple[int, int], ...]:
    if piece_type == chess.ROOK:
        return _ROOK_DIRS
    if piece_type == chess.BISHOP:
        return _BISHOP_DIRS
    return _ROOK_DIRS + _BISHOP_DIRS


def _ray(square: chess.Square, df: int, dr: int) -> Iterator[chess.Square]:
    f, r = chess.square_file(square) + df, chess.square_rank(square) + dr
    while 0 <= f < 8 and 0 <= r < 8:
        yield chess.square(f, r)
        f, r = f + df, r + dr


def _first_two(board: chess.Board, square: chess.Square, df: int, dr: int) -> tuple[chess.Square | None, ...]:
    found: list[chess.Square] = []
    for sq in _ray(square, df, dr):
        if board.piece_at(sq) is not None:
            found.append(sq)
            if len(found) == 2:
                break
    return tuple(found) + (None,) * (2 - len(found))


def pins(
    board: chess.Board, victim: chess.Color
) -> list[tuple[chess.Square, chess.Square, chess.Square, bool]]:
    """(pinner, pinned, behind, absolute) for each pin against `victim`'s pieces."""
    result = []
    for piece_type in SLIDERS:
        for slider in board.pieces(piece_type, not victim):
            for df, dr in _directions(piece_type):
                first, second = _first_two(board, slider, df, dr)
                if first is None or second is None:
                    continue
                a, b = board.piece_at(first), board.piece_at(second)
                if a is None or b is None or a.color != victim or b.color != victim:
                    continue
                if a.piece_type == chess.KING:
                    continue
                if b.piece_type == chess.KING:
                    result.append((slider, first, second, True))
                elif VALUES[b.piece_type] > VALUES[a.piece_type]:
                    result.append((slider, first, second, False))
    return result


def _fork_targets(board: chess.Board, square: chess.Square, actor: chess.Color) -> list[chess.Square]:
    """Enemy pieces (not pawns) attacked from `square` that are real targets: the king, anything
    worth more than the attacker, or a piece the attacker could win outright (undefended or
    under-defended), as long as it can't simply take the attacker and come out ahead."""
    attacker = board.piece_at(square)
    if attacker is None:
        return []
    # The same position with the attacker to move, to ask "could I win this piece right now?"
    probe = board.copy(stack=False)
    probe.turn = actor
    probe.ep_square = None
    targets = []
    for target in board.attacks(square):
        victim = board.piece_at(target)
        if victim is None or victim.color == actor or victim.piece_type == chess.PAWN:
            continue
        bigger = victim.piece_type == chess.KING or VALUES[victim.piece_type] > VALUES[attacker.piece_type]
        # A loose piece is a target unless it can just take the attacker and come out ahead.
        loose = not board.attackers(not actor, target) and not any(
            m.from_square == target and see(board, m) > 0 for m in captures_on(board, square)
        )
        underdefended = best_capture(probe, target)[0] > 0
        if bigger or loose or underdefended:
            targets.append(target)
    return targets


# --- detectors -------------------------------------------------------------------------------


def _fork(c: _Ctx) -> Iterator[Motif]:
    for k in c.actor_plies():
        move = c.line.moves[k]
        after = c.line.boards[k + 1]
        piece = after.piece_at(move.to_square)
        if piece is None or piece.piece_type == chess.KING or _in_bad_spot(after, move.to_square):
            continue
        targets = _fork_targets(after, move.to_square, c.actor)
        if len(targets) < 2:
            continue
        wins_target = c.first_capture_of(k + 1, set(targets)) is not None and c.gain(k) > 0
        # A forking check that leads to mate counts too, but not the mating move itself.
        heavy = any(after.piece_type_at(t) in (chess.ROOK, chess.QUEEN) for t in targets)
        forks_into_mate = after.is_check() and heavy and c.mates() and k + 1 < c.settle
        if wins_target or forks_into_mate:
            types = {after.piece_type_at(t) for t in targets}
            yield Motif(
                "fork",
                k,
                move.to_square,
                targets,
                {"piece": piece.piece_type, "royal": {chess.KING, chess.QUEEN} <= types},
            )


def _pin(c: _Ctx) -> Iterator[Motif]:
    """A pin that matters: the pinned piece can't escape an attack, or can't take something.

    Absolute pins (to the king) are judged like lichess does; relative pins (to a bigger piece)
    count when the line then wins the pinned piece.
    """
    for k in c.actor_plies():
        if not c.pays_off(k):
            continue
        after = c.line.boards[k + 1]
        for square in chess.SquareSet(after.occupied_co[c.enemy]):
            piece = after.piece_at(square)
            if piece is None or piece.piece_type == chess.KING or not after.is_pinned(c.enemy, square):
                continue
            ray = after.pin(c.enemy, square)
            pinner = next((sq for sq in after.attackers(c.actor, square) if sq in ray), None)
            king = after.king(c.enemy)
            # The pinned piece can't escape an attack from along the pin line: either it's worth
            # more than the attacker, or it's undefended and would otherwise just step away.
            for attacker in after.attackers(c.actor, square):
                if attacker not in ray:
                    continue
                bigger = VALUES[piece.piece_type] > VALUES[after.piece_type_at(attacker) or chess.KING]
                stuck = (
                    not after.attackers(c.enemy, square)
                    and attacker not in after.attacks(square)
                    and any(
                        m.from_square == square and m.to_square not in ray for m in after.pseudo_legal_moves
                    )
                )
                if bigger or stuck:
                    yield _pin_motif(k, attacker, square, king, piece.piece_type, "wins_pinned_piece", True)
                    return
            # The pinned piece attacks something of ours but can't take it.
            for target in after.attacks(square):
                ours = after.piece_at(target)
                if ours is None or ours.color != c.actor or target in ray:
                    continue
                if VALUES[ours.piece_type] > VALUES[piece.piece_type] or not after.attackers(c.actor, target):
                    yield _pin_motif(k, pinner, square, king, piece.piece_type, "pinned_defender", True)
                    return
        for pinner, pinned, behind, absolute in pins(after, c.enemy):
            pinned_type = after.piece_type_at(pinned) or chess.PAWN
            behind_type = after.piece_type_at(behind) or chess.PAWN
            # Relative pins worth naming: a piece (not a pawn) pinned to a queen or rook.
            if absolute or pinned_type == chess.PAWN or behind_type not in (chess.QUEEN, chess.ROOK):
                continue
            if c.first_capture_on(k + 1, {pinned}) is not None and c.gain(k) > 0:
                yield _pin_motif(k, pinner, pinned, behind, pinned_type, "wins_pinned_piece", False)
                return


def _pin_motif(
    k: int,
    pinner: chess.Square | None,
    pinned: chess.Square,
    behind: chess.Square | None,
    pinned_type: chess.PieceType,
    use: str,
    absolute: bool,
) -> Motif:
    return Motif(
        "pin",
        k,
        pinner,
        [pinned] + ([behind] if behind is not None else []),
        {"absolute": absolute, "use": use, "pinned": pinned_type},
    )


def _skewer(c: _Ctx) -> Iterator[Motif]:
    for k in c.actor_plies(stop=c.settle - 2):
        move = c.line.moves[k]
        after = c.line.boards[k + 1]
        piece = after.piece_at(move.to_square)
        if piece is None or piece.piece_type not in SLIDERS:
            continue
        for df, dr in _directions(piece.piece_type):
            front, back = _first_two(after, move.to_square, df, dr)
            if front is None or back is None:
                continue
            a, b = after.piece_at(front), after.piece_at(back)
            if a is None or b is None or a.color != c.enemy or b.color != c.enemy:
                continue
            if not (a.piece_type == chess.KING or VALUES[a.piece_type] > VALUES[b.piece_type]):
                continue
            steps_aside = c.line.moves[k + 1].from_square == front
            takes_back = c.line.moves[k + 2].to_square == back and c.line.boards[k + 2].is_capture(
                c.line.moves[k + 2]
            )
            if steps_aside and takes_back and c.gain(k) > 0:
                yield Motif(
                    "skewer", k, move.to_square, [front, back], {"front": a.piece_type, "back": b.piece_type}
                )
                return


def _discovered(c: _Ctx) -> Iterator[Motif]:
    for k in c.actor_plies():
        move = c.line.moves[k]
        before, after = c.line.boards[k], c.line.boards[k + 1]
        # Discovered check: the king is checked by a piece other than the one that moved.
        if before.is_castling(move):
            continue
        hidden = [sq for sq in after.checkers() if sq != move.to_square]
        if hidden and c.pays_off(k):
            yield Motif(
                "discovered_check",
                k,
                hidden[0],
                [after.king(c.enemy) or 0],
                {
                    "moved": before.piece_type_at(move.from_square),
                    "line_piece": after.piece_type_at(hidden[0]),
                },
            )
            return
    # Discovered attack: a piece moves out of the way and the piece behind it captures.
    for j in c.actor_plies():
        if j < 2:
            continue
        capture, board = c.line.moves[j], c.line.boards[j]
        if not board.is_capture(capture) or board.piece_type_at(capture.from_square) not in SLIDERS:
            continue
        unmasking = c.line.moves[j - 2]
        reply = c.line.moves[j - 1]
        between = chess.SquareSet(chess.between(capture.from_square, capture.to_square))
        if (
            unmasking.from_square in between
            and reply.to_square != capture.to_square
            and capture.to_square != unmasking.to_square
            and capture.from_square != unmasking.to_square
            and not c.line.boards[j - 2].is_castling(unmasking)
            and c.pays_off(j - 2)
        ):
            yield Motif(
                "discovered_attack",
                j - 2,
                capture.from_square,
                [capture.to_square],
                {
                    "moved": c.line.boards[j - 2].piece_type_at(unmasking.from_square),
                    "line_piece": board.piece_type_at(capture.from_square),
                },
            )
            return


def _double_check(c: _Ctx) -> Iterator[Motif]:
    for k in c.actor_plies():
        after = c.line.boards[k + 1]
        if len(after.checkers()) >= 2 and c.pays_off(k):
            yield Motif("double_check", k, c.line.moves[k].to_square, [after.king(c.enemy) or 0])
            return


def _removal_of_defender(c: _Ctx) -> Iterator[Motif]:
    for k in c.actor_plies(stop=c.settle - 2):
        move = c.line.moves[k]
        before = c.line.boards[k]
        if not before.is_capture(move) or before.is_en_passant(move):
            continue
        defender_sq = move.to_square
        defender = before.piece_at(defender_sq)
        if defender is None:
            continue
        for target in before.attacks(defender_sq):
            victim = before.piece_at(target)
            if victim is None or victim.color != c.enemy or victim.piece_type == chess.KING:
                continue
            if best_capture(before, target)[0] > 0:
                continue  # it was already loose; nothing to remove
            if c.first_capture_on(k + 2, {target}) is not None and c.gain(k) > 0:
                yield Motif(
                    "removal_of_defender",
                    k,
                    defender_sq,
                    [defender_sq, target],
                    {"defender": defender.piece_type, "target": victim.piece_type},
                )
                return


def _deflection(c: _Ctx) -> Iterator[Motif]:
    for k in c.actor_plies(stop=c.settle - 2):
        reply = c.line.moves[k + 1]
        mid = c.line.boards[k + 1]
        defender = mid.piece_at(reply.from_square)
        if defender is None or defender.piece_type == chess.KING:
            continue
        follow = c.line.moves[k + 2]
        after_reply = c.line.boards[k + 2]
        duty = follow.to_square
        if duty == reply.to_square or duty not in mid.attacks(reply.from_square):
            continue
        if duty in after_reply.attacks(reply.to_square):
            continue  # still guarding it from the new square
        decisive = after_reply.is_capture(follow) or c.line.boards[k + 3].is_check()
        if decisive and c.pays_off(k):
            yield Motif(
                "deflection",
                k,
                c.line.moves[k].to_square,
                [reply.from_square, duty],
                {"defender": defender.piece_type},
            )
            return


def _attraction(c: _Ctx) -> Iterator[Motif]:
    for k in c.actor_plies(stop=c.settle - 2):
        move = c.line.moves[k]
        square = move.to_square
        reply = c.line.moves[k + 1]
        if reply.to_square != square or not c.line.boards[k + 1].is_capture(reply):
            continue
        lured = c.line.boards[k + 2].piece_at(square)
        follow = c.line.moves[k + 2]
        after = c.line.boards[k + 3]
        if lured is None or not (after.is_check() or square in after.attacks(follow.to_square)):
            continue
        lost = VALUES[c.line.boards[k].piece_type_at(move.from_square) or chess.PAWN]
        if lost > captured_value(c.line.boards[k], move) and c.pays_off(k):
            yield Motif("attraction", k, square, [square], {"lured": lured.piece_type})
            return


def _trapped_piece(c: _Ctx) -> Iterator[Motif]:
    """A piece that is attacked and has nowhere safe to go, and the line then wins it."""
    for j in c.actor_plies():
        if j < 2:
            continue
        capture, board = c.line.moves[j], c.line.boards[j]
        victim = board.piece_at(capture.to_square)
        if not board.is_capture(capture) or victim is None or victim.piece_type in (chess.PAWN, chess.KING):
            continue
        reply = c.line.moves[j - 1]
        square = reply.from_square if reply.to_square == capture.to_square else capture.to_square
        position = c.line.boards[j - 1]  # the trapped side to move
        if _is_trapped(position, square) and c.gain(j - 2) > 0:
            yield Motif("trapped_piece", j - 2, square, [square], {"piece": victim.piece_type})
            return


def _in_bad_spot(board: chess.Board, square: chess.Square) -> bool:
    """Attacked, and either undefended or attackable by something cheaper."""
    piece = board.piece_at(square)
    if piece is None:
        return False
    attackers = board.attackers(not piece.color, square)
    if not attackers:
        return False
    if not board.attackers(piece.color, square):
        return True
    return any(
        VALUES[board.piece_type_at(a) or chess.KING] < VALUES[piece.piece_type]
        for a in attackers
        if board.piece_type_at(a) != chess.KING
    )


def _is_trapped(board: chess.Board, square: chess.Square) -> bool:
    piece = board.piece_at(square)
    if piece is None or piece.piece_type in (chess.PAWN, chess.KING) or piece.color != board.turn:
        return False
    if board.is_check() or board.is_pinned(piece.color, square) or not _in_bad_spot(board, square):
        return False
    for move in board.legal_moves:
        if move.from_square != square:
            continue
        if captured_value(board, move) >= VALUES[piece.piece_type]:
            return False
        board.push(move)
        try:
            if not _in_bad_spot(board, move.to_square):
                return False
        finally:
            board.pop()
    return True


def _captures_type(c: _Ctx, start: int, piece_type: chess.PieceType) -> bool:
    for k in range(start, min(c.settle, len(c.line))):
        board = c.line.boards[k]
        move = c.line.moves[k]
        if board.turn == c.actor and board.piece_type_at(move.to_square) == piece_type:
            return True
    return False


def _zwischenzug(c: _Ctx) -> Iterator[Motif]:
    for k in c.actor_plies():
        if k == 0:
            continue
        prev, prev_board = c.line.moves[k - 1], c.line.boards[k - 1]
        if not prev_board.is_capture(prev):
            continue
        square = prev.to_square
        before = c.line.boards[k]
        recaptures = captures_on(before, square)
        if not recaptures or max(see(before, m) for m in recaptures) < 0:
            continue
        move = c.line.moves[k]
        if move.to_square == square or not (before.gives_check(move) or before.is_capture(move)):
            continue
        if c.first_capture_on(k + 2, {square}) is not None and c.gain(k) > 0:
            yield Motif("zwischenzug", k, move.to_square, [square], {})
            return


def _promotion(c: _Ctx) -> Iterator[Motif]:
    for k in c.actor_plies(stop=len(c.line)):
        move = c.line.moves[k]
        if move.promotion:
            name = "promotion" if move.promotion == chess.QUEEN else "underpromotion"
            yield Motif(name, k, move.to_square, [move.to_square], {"piece": move.promotion})
            return


def _hanging_piece(c: _Ctx) -> Iterator[Motif]:
    """The first move simply takes an undefended piece (not a recapture in a trade)."""
    k = next(c.actor_plies(), None)
    if k is None:
        return
    move = c.line.moves[k]
    before = c.line.boards[k]
    victim = before.piece_at(move.to_square)
    if not before.is_capture(move) or victim is None or victim.piece_type == chess.PAWN:
        return
    if before.attackers(c.enemy, move.to_square):
        return  # defended: winning it would be a different idea
    prev = c.previous(k)
    if prev is not None:
        prev_board, prev_move = prev
        traded = prev_board.piece_at(prev_move.to_square)
        if (
            prev_move.to_square == move.to_square
            and traded is not None
            and VALUES[traded.piece_type] >= VALUES[victim.piece_type]
        ):
            return  # just taking back in an exchange
    if c.gain(k) >= VALUES[victim.piece_type] - VALUES[chess.PAWN] or c.mates():
        yield Motif(
            "hanging_piece",
            k,
            move.to_square,
            [move.to_square],
            {"victim": victim.piece_type, "defended": False},
        )


def _sacrifice(c: _Ctx) -> Iterator[Motif]:
    for k in c.actor_plies():
        offered = sacrificed_material(c.line.boards[k], c.line.moves[k])
        if offered >= 200 and (c.mates() or c.gain(k) >= 0):
            yield Motif("sacrifice", k, c.line.moves[k].to_square, [], {"offered": offered})
            return


def _quiet_move(c: _Ctx) -> Iterator[Motif]:
    k = next(c.actor_plies(), None)
    if k is None:
        return
    move, board = c.line.moves[k], c.line.boards[k]
    forcing = board.is_capture(move) or board.gives_check(move) or move.promotion
    if not forcing and c.pays_off(k) and (c.mates() or c.gain(k) >= 200):
        yield Motif("quiet_move", k, move.to_square, [], {})


def _mate(c: _Ctx) -> Iterator[Motif]:
    end = c.line.end
    if not (end.is_checkmate() and end.turn != c.actor):
        return
    plies = list(c.actor_plies(stop=len(c.line)))
    if plies:
        yield Motif(
            "mate",
            plies[0],
            c.line.moves[plies[-1]].to_square,
            [end.king(c.enemy) or 0],
            {"pattern": mate_pattern(end), "mate_in": len(plies)},
        )


def _perpetual(c: _Ctx) -> Iterator[Motif]:
    plies = list(c.actor_plies(stop=len(c.line)))
    if len(plies) < 3 or not all(c.line.boards[k].gives_check(c.line.moves[k]) for k in plies):
        return
    seen: set[str] = set()
    for board in c.line.boards:
        key = board.epd()
        if key in seen:
            yield Motif("perpetual_check", plies[0], None, [], {})
            return
        seen.add(key)


DETECTORS = (
    _mate,
    _double_check,
    _discovered,
    _fork,
    _skewer,
    _pin,
    _removal_of_defender,
    _deflection,
    _attraction,
    _trapped_piece,
    _zwischenzug,
    _promotion,
    _hanging_piece,
    _sacrifice,
    _quiet_move,
    _perpetual,
)


def detect_motifs(line: Line, actor: chess.Color) -> list[Motif]:
    """All motifs the actor executes in `line`, ordered by move then by specificity."""
    if not line.moves:
        return []
    c = _Ctx(line, actor, line.settle_point(actor))
    found = [motif for detector in DETECTORS for motif in detector(c)]
    return sorted(found, key=lambda m: (m.ply, PRIORITY.index(m.name)))
