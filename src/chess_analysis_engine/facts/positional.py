"""Positional features (pawn structure, king safety, development, activity) and their changes.

These explain moves that lose without a tactic. We compare the calm end of the best line with
the calm end of the played line and keep only clear, concrete differences.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

_MINOR_HOME = {
    chess.WHITE: {
        chess.B1: chess.KNIGHT,
        chess.G1: chess.KNIGHT,
        chess.C1: chess.BISHOP,
        chess.F1: chess.BISHOP,
    },
    chess.BLACK: {
        chess.B8: chess.KNIGHT,
        chess.G8: chess.KNIGHT,
        chess.C8: chess.BISHOP,
        chess.F8: chess.BISHOP,
    },
}
_CENTER = [chess.D4, chess.E4, chess.D5, chess.E5]


@dataclass(frozen=True)
class Features:
    isolated: frozenset[chess.Square]
    doubled_files: frozenset[int]
    passed: frozenset[chess.Square]
    king_shield: int
    king_open_files: int
    king_zone_attackers: int
    castled: bool
    can_castle: bool
    bishop_pair: bool
    undeveloped: int
    mobility: int
    rooks_on_open_files: int
    outposts: frozenset[chess.Square]
    center: int


def _pawn_files(board: chess.Board, color: chess.Color) -> dict[int, list[chess.Square]]:
    files: dict[int, list[chess.Square]] = {}
    for sq in board.pieces(chess.PAWN, color):
        files.setdefault(chess.square_file(sq), []).append(sq)
    return files


def _is_passed(board: chess.Board, square: chess.Square, color: chess.Color) -> bool:
    file, rank = chess.square_file(square), chess.square_rank(square)
    ahead = range(rank + 1, 8) if color == chess.WHITE else range(rank - 1, -1, -1)
    for enemy in board.pieces(chess.PAWN, not color):
        if abs(chess.square_file(enemy) - file) <= 1 and chess.square_rank(enemy) in ahead:
            return False
    return True


def _king_zone(king: chess.Square) -> chess.SquareSet:
    return chess.SquareSet(chess.BB_KING_ATTACKS[king]) | chess.SquareSet.from_square(king)


def features(board: chess.Board, color: chess.Color) -> Features:
    files = _pawn_files(board, color)
    isolated = frozenset(
        sq for f, squares in files.items() for sq in squares if f - 1 not in files and f + 1 not in files
    )
    doubled = frozenset(f for f, squares in files.items() if len(squares) > 1)
    passed = frozenset(sq for sq in board.pieces(chess.PAWN, color) if _is_passed(board, sq, color))

    king = board.king(color)
    shield = open_files = zone_attackers = 0
    castled = False
    if king is not None:
        kf, kr = chess.square_file(king), chess.square_rank(king)
        forward = 1 if color == chess.WHITE else -1
        for f in (kf - 1, kf, kf + 1):
            if not 0 <= f < 8:
                continue
            for dr in (1, 2):
                r = kr + forward * dr
                if (
                    0 <= r < 8
                    and board.piece_type_at(chess.square(f, r)) == chess.PAWN
                    and board.color_at(chess.square(f, r)) == color
                ):
                    shield += 1
                    break
            if f not in files:
                open_files += 1
        zone = _king_zone(king)
        zone_attackers = len(
            {a for sq in zone for a in board.attackers(not color, sq) if board.piece_type_at(a) != chess.PAWN}
        )
        home_rank = 0 if color == chess.WHITE else 7
        castled = kr == home_rank and kf in (1, 2, 6, 7)

    undeveloped = sum(
        1
        for sq, pt in _MINOR_HOME[color].items()
        if board.piece_type_at(sq) == pt and board.color_at(sq) == color
    )
    mobility = 0
    for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        for sq in board.pieces(pt, color):
            for target in board.attacks(sq):
                if board.color_at(target) == color:
                    continue
                if any(board.piece_type_at(a) == chess.PAWN for a in board.attackers(not color, target)):
                    continue
                mobility += 1
    pawn_files_all = set(files) | set(_pawn_files(board, not color))
    rooks_open = sum(
        1 for sq in board.pieces(chess.ROOK, color) if chess.square_file(sq) not in pawn_files_all
    )
    outposts = frozenset(
        sq
        for pt in (chess.KNIGHT, chess.BISHOP)
        for sq in board.pieces(pt, color)
        if _is_outpost(board, sq, color)
    )
    center = sum(len(board.attackers(color, sq)) for sq in _CENTER)
    return Features(
        isolated=isolated,
        doubled_files=doubled,
        passed=passed,
        king_shield=shield,
        king_open_files=open_files,
        king_zone_attackers=zone_attackers,
        castled=castled,
        can_castle=board.has_castling_rights(color),
        bishop_pair=len(board.pieces(chess.BISHOP, color)) >= 2,
        undeveloped=undeveloped,
        mobility=mobility,
        rooks_on_open_files=rooks_open,
        outposts=outposts,
        center=center,
    )


def _is_outpost(board: chess.Board, square: chess.Square, color: chess.Color) -> bool:
    """In the enemy half, protected by a pawn, and no enemy pawn can ever attack it."""
    rank = chess.square_rank(square)
    if (color == chess.WHITE and rank < 4) or (color == chess.BLACK and rank > 3):
        return False
    if not any(board.piece_type_at(a) == chess.PAWN for a in board.attackers(color, square)):
        return False
    file = chess.square_file(square)
    for enemy in board.pieces(chess.PAWN, not color):
        ef, er = chess.square_file(enemy), chess.square_rank(enemy)
        if abs(ef - file) == 1 and (
            (color == chess.WHITE and er > rank) or (color == chess.BLACK and er < rank)
        ):
            return False
    return True


@dataclass(frozen=True)
class PositionalDiff:
    feature: str
    weight: float
    detail: dict


def compare(best_end: chess.Board, played_end: chess.Board, color: chess.Color) -> list[PositionalDiff]:
    """Concrete ways the best line's end position is better for `color` than the played line's."""
    good, bad = features(best_end, color), features(played_end, color)
    their_good, their_bad = features(best_end, not color), features(played_end, not color)
    diffs: list[PositionalDiff] = []

    new_isolated = bad.isolated - good.isolated
    if len(bad.isolated) > len(good.isolated) and new_isolated:
        diffs.append(
            PositionalDiff(
                "isolated_pawn", 1.0, {"squares": sorted(chess.square_name(s) for s in new_isolated)}
            )
        )
    if len(bad.doubled_files) > len(good.doubled_files):
        files = sorted(chess.FILE_NAMES[f] for f in bad.doubled_files - good.doubled_files)
        if files:
            diffs.append(PositionalDiff("doubled_pawns", 1.0, {"files": files}))
    new_passed = their_bad.passed - their_good.passed
    if len(their_bad.passed) > len(their_good.passed) and new_passed:
        diffs.append(
            PositionalDiff(
                "passed_pawn_allowed", 1.6, {"squares": sorted(chess.square_name(s) for s in new_passed)}
            )
        )
    our_new_passed = good.passed - bad.passed
    if len(good.passed) > len(bad.passed) and our_new_passed:
        diffs.append(
            PositionalDiff(
                "passed_pawn_missed", 1.3, {"squares": sorted(chess.square_name(s) for s in our_new_passed)}
            )
        )
    if bad.king_shield < good.king_shield or bad.king_open_files > good.king_open_files:
        diffs.append(
            PositionalDiff(
                "king_safety",
                1.5 + 0.3 * (bad.king_zone_attackers - good.king_zone_attackers),
                {"shield_lost": good.king_shield - bad.king_shield, "open_files": bad.king_open_files},
            )
        )
    if good.castled and not bad.castled and not bad.can_castle:
        diffs.append(PositionalDiff("castling_lost", 1.4, {}))
    if good.bishop_pair and not bad.bishop_pair:
        diffs.append(PositionalDiff("bishop_pair", 0.8, {}))
    if bad.undeveloped > good.undeveloped:
        diffs.append(
            PositionalDiff(
                "development", 0.9 * (bad.undeveloped - good.undeveloped), {"count": bad.undeveloped}
            )
        )
    if good.mobility - bad.mobility >= 6:
        diffs.append(
            PositionalDiff(
                "activity", 0.1 * (good.mobility - bad.mobility), {"difference": good.mobility - bad.mobility}
            )
        )
    if len(good.outposts) > len(bad.outposts):
        squares = sorted(chess.square_name(s) for s in good.outposts - bad.outposts)
        if squares:
            diffs.append(PositionalDiff("outpost_missed", 1.0, {"squares": squares}))
    if len(their_bad.outposts) > len(their_good.outposts):
        squares = sorted(chess.square_name(s) for s in their_bad.outposts - their_good.outposts)
        if squares:
            diffs.append(PositionalDiff("outpost_allowed", 1.1, {"squares": squares}))
    if good.rooks_on_open_files > bad.rooks_on_open_files:
        diffs.append(PositionalDiff("open_file", 0.7, {}))
    return sorted(diffs, key=lambda d: -d.weight)


def opening_principles(board: chess.Board, move: chess.Move) -> list[str]:
    """Opening habits a move breaks (only meaningful in the first dozen moves)."""
    if board.fullmove_number > 12:
        return []
    color = board.turn
    piece = board.piece_type_at(move.from_square)
    broken: list[str] = []
    undeveloped = sum(
        1
        for sq, pt in _MINOR_HOME[color].items()
        if board.piece_type_at(sq) == pt and board.color_at(sq) == color
    )
    if (
        piece == chess.QUEEN
        and board.fullmove_number <= 6
        and not board.is_capture(move)
        and undeveloped >= 3
    ):
        broken.append("early_queen")
    if piece == chess.KING and not board.is_castling(move) and board.has_castling_rights(color):
        broken.append("king_walk")
    if (
        piece in (chess.KNIGHT, chess.BISHOP)
        and move.from_square not in _MINOR_HOME[color]
        and undeveloped >= 2
        and not board.is_capture(move)
    ):
        broken.append("same_piece_twice")
    king_side = board.king(color) in (chess.E1, chess.E8, chess.G1, chess.G8)
    f_or_g_pawn = piece == chess.PAWN and chess.square_file(move.from_square) in (5, 6)
    if f_or_g_pawn and king_side and not board.is_capture(move):
        broken.append("weakening_pawn_move")
    return broken
