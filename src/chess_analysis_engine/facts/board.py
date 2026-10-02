"""Board-level building blocks: piece values, material, and static exchange evaluation.

SEE is computed with legal moves only, so pins and x-ray attackers are handled naturally:
after each capture the next legal recapture is generated from the new position.
"""

from __future__ import annotations

import chess

VALUES: dict[chess.PieceType, int] = {
    chess.PAWN: 100,
    chess.KNIGHT: 300,
    chess.BISHOP: 300,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}
# Order in which a side prefers to recapture (the king last: it can only take undefended pieces).
_CAPTURE_ORDER = {**VALUES, chess.KING: 10_000}

PIECE_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}


def piece_name(piece_type: chess.PieceType) -> str:
    return PIECE_NAMES[piece_type]


def material(board: chess.Board, color: chess.Color) -> int:
    return sum(VALUES[pt] * len(board.pieces(pt, color)) for pt in VALUES)


def material_balance(board: chess.Board, color: chess.Color) -> int:
    """Material of `color` minus the opponent's, in centipawns."""
    return material(board, color) - material(board, not color)


def captured_value(board: chess.Board, move: chess.Move) -> int:
    if board.is_en_passant(move):
        return VALUES[chess.PAWN]
    victim = board.piece_at(move.to_square)
    if victim is None or victim.color == board.turn:  # castling encoded as king-takes-rook
        return 0
    return VALUES[victim.piece_type]


def move_gain(board: chess.Board, move: chess.Move) -> int:
    """Immediate material change of a move: what it captures plus any promotion bonus."""
    gain = captured_value(board, move)
    if move.promotion:
        gain += VALUES[move.promotion] - VALUES[chess.PAWN]
    return gain


def captures_on(board: chess.Board, square: chess.Square) -> list[chess.Move]:
    """Legal captures onto `square` by the side to move (queen promotions only)."""
    return [
        m
        for m in board.generate_legal_captures(to_mask=chess.BB_SQUARES[square])
        if m.promotion in (None, chess.QUEEN)
    ]


def see(board: chess.Board, move: chess.Move) -> int:
    """Static exchange evaluation: net material the side to move wins with `move`, assuming both
    sides keep recapturing on the destination square with their cheapest piece, and either side
    may stop when continuing would lose material."""
    gain = move_gain(board, move)
    board.push(move)
    try:
        replies = captures_on(board, move.to_square)
        if not replies:
            return gain
        reply = min(replies, key=lambda m: _CAPTURE_ORDER[board.piece_type_at(m.from_square) or chess.PAWN])
        return gain - max(0, see(board, reply))
    finally:
        board.pop()


def best_capture(board: chess.Board, square: chess.Square) -> tuple[int, chess.Move | None]:
    """Most material the side to move can win by capturing on `square` (0 if none)."""
    best_value, best_move = 0, None
    for move in captures_on(board, square):
        value = see(board, move)
        if value > best_value:
            best_value, best_move = value, move
    return best_value, best_move


def winning_captures(board: chess.Board) -> list[tuple[int, chess.Move]]:
    """All captures the side to move has that win material by SEE, best first."""
    found: dict[chess.Square, tuple[int, chess.Move]] = {}
    for move in board.generate_legal_captures():
        if move.promotion not in (None, chess.QUEEN):
            continue
        value = see(board, move)
        if value > 0 and value > found.get(move.to_square, (0, move))[0]:
            found[move.to_square] = (value, move)
    return sorted(found.values(), key=lambda item: -item[0])


def sacrificed_material(board: chess.Board, move: chess.Move) -> int:
    """Material the mover puts on offer with `move`, in the static exchange sense: either a
    capture that loses the exchange, or something left that the opponent can win by capturing.

    Positive values mean a real offer; a move that keeps everything protected returns 0.
    """
    offered = 0
    is_capture = board.is_capture(move)
    if is_capture:
        offered = max(0, -see(board, move))
    board.push(move)
    try:
        if board.is_checkmate():
            return 0
        for capture in board.generate_legal_captures():
            if is_capture and capture.to_square == move.to_square:
                continue  # already counted by the SEE of the move itself
            if capture.promotion not in (None, chess.QUEEN):
                continue
            offered = max(offered, see(board, capture))
    finally:
        board.pop()
    return offered


def is_recapture(board: chess.Board, move: chess.Move) -> bool:
    """True if `move` captures on the square where the opponent just captured."""
    if not board.move_stack or not board.is_capture(move):
        return False
    last = board.move_stack[-1]
    board.pop()
    try:
        was_capture = board.is_capture(last)
    finally:
        board.push(last)
    return was_capture and last.to_square == move.to_square
