"""Names for well-known checkmate patterns."""

from __future__ import annotations

import chess

PATTERN_NAMES = {
    "smothered_mate": "smothered mate",
    "back_rank_mate": "back-rank mate",
    "anastasia_mate": "Anastasia's mate",
    "arabian_mate": "Arabian mate",
    "boden_mate": "Boden's mate",
    "double_bishop_mate": "double-bishop mate",
    "dovetail_mate": "dovetail mate",
    "double_check_mate": "double-check mate",
}

_CORNERS = {chess.A1, chess.H1, chess.A8, chess.H8}


def _adjacent(square: chess.Square) -> chess.SquareSet:
    return chess.SquareSet(chess.BB_KING_ATTACKS[square])


def mate_pattern(board: chess.Board) -> str | None:
    """Pattern name for a checkmated position (the side to move is mated), else None."""
    if not board.is_checkmate():
        return None
    loser = board.turn
    winner = not loser
    king = board.king(loser)
    if king is None:
        return None
    checkers = list(board.checkers())
    if len(checkers) > 1:
        return "double_check_mate"
    checker = checkers[0]
    checker_type = board.piece_type_at(checker)
    around = _adjacent(king)
    own_blockers = [s for s in around if board.color_at(s) == loser]

    if checker_type == chess.KNIGHT and len(own_blockers) == len(around):
        return "smothered_mate"

    back_rank = 0 if loser == chess.WHITE else 7
    if (
        checker_type in (chess.ROOK, chess.QUEEN)
        and chess.square_rank(king) == back_rank
        and chess.square_rank(checker) == back_rank
    ):
        forward = [s for s in around if chess.square_rank(s) != back_rank]
        if forward and all(board.color_at(s) == loser for s in forward):
            return "back_rank_mate"

    knight_guard = any(board.piece_type_at(d) == chess.KNIGHT for d in board.attackers(winner, checker))
    if checker_type == chess.ROOK and king in _CORNERS and checker in around and knight_guard:
        return "arabian_mate"

    edge_file = chess.square_file(king) in (0, 7)
    if (
        edge_file
        and checker_type in (chess.ROOK, chess.QUEEN)
        and chess.square_file(checker) == chess.square_file(king)
        and own_blockers
    ):
        knights = board.pieces(chess.KNIGHT, winner)
        if any(chess.BB_KNIGHT_ATTACKS[n] & int(around) for n in knights):
            return "anastasia_mate"

    bishops = list(board.pieces(chess.BISHOP, winner))
    if len(bishops) >= 2 and _only_bishops_cover(board, king, winner):
        left = [b for b in bishops if chess.square_file(b) < chess.square_file(king)]
        right = [b for b in bishops if chess.square_file(b) > chess.square_file(king)]
        return "boden_mate" if left and right else "double_bishop_mate"

    if checker_type == chess.QUEEN and _is_dovetail(board, king, checker, winner):
        return "dovetail_mate"
    return None


def _only_bishops_cover(board: chess.Board, king: chess.Square, winner: chess.Color) -> bool:
    """Every attacker of the king and its surrounding squares is a bishop."""
    for square in [*_adjacent(king), king]:
        for attacker in board.attackers(winner, square):
            if board.piece_type_at(attacker) != chess.BISHOP:
                return False
    return True


def _is_dovetail(board: chess.Board, king: chess.Square, queen: chess.Square, winner: chess.Color) -> bool:
    """Queen mates from a diagonally adjacent square, unaided; the king's own pieces block it in."""
    if chess.square_file(king) in (0, 7) or chess.square_rank(king) in (0, 7):
        return False
    if chess.square_distance(queen, king) != 1 or chess.square_file(queen) == chess.square_file(king):
        return False
    if chess.square_rank(queen) == chess.square_rank(king):
        return False
    for square in _adjacent(king):
        if square == queen:
            continue
        attackers = list(board.attackers(winner, square))
        if attackers == [queen]:
            if board.piece_at(square) is not None:
                return False
        elif attackers:
            return False
    return True
