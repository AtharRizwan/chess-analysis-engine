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


def exposure(board: chess.Board, side: chess.Color) -> dict[chess.Square, int]:
    """What `side` could win on each square by capturing there now (SEE), as if it were its turn.

    Asked of the side *not* to move, this is "what is en prise": a null move hands over the turn
    (also when the side to move is in check — we only ask what is attacked, not what is legal).
    """
    b = board.copy(stack=False)
    if b.turn != side:
        b.push(chess.Move.null())
    found: dict[chess.Square, int] = {}
    for capture in b.generate_pseudo_legal_captures():
        if capture.promotion not in (None, chess.QUEEN) or b.piece_type_at(capture.to_square) == chess.KING:
            continue
        if b.is_into_check(capture):
            continue
        value = see(b, capture)
        if value > found.get(capture.to_square, 0):
            found[capture.to_square] = value
    return found


def sacrificed_material(board: chess.Board, move: chess.Move) -> int:
    """Material that `move` itself puts on offer, in the static exchange sense.

    That is a capture that loses the exchange, or something the opponent can win after the move that
    they couldn't win before it (pieces already hanging don't count: every move would "offer" them).
    Material the move captures pays for what it leaves en prise, so winning a rook while leaving a
    knight hanging is no sacrifice. King moves and mates offer nothing.
    """
    if board.piece_type_at(move.from_square) == chess.KING:
        return 0
    mover = board.turn
    is_capture = board.is_capture(move)
    won = see(board, move) if is_capture else 0
    before = exposure(board, not mover)
    board.push(move)
    try:
        if board.is_checkmate():
            return 0
        after = exposure(board, not mover)
    finally:
        board.pop()
    offered = max(0, -won)
    for square, value in after.items():
        if is_capture and square == move.to_square:
            continue  # already counted by the SEE of the move itself
        was = before.get(move.from_square if square == move.to_square else square, 0)
        offered = max(offered, value - was - max(0, won))
    return offered


def rescues_piece(board: chess.Board, move: chess.Move) -> bool:
    """True if the moved piece was en prise before the move (moving it is the obvious thing to do)."""
    return exposure(board, not board.turn).get(move.from_square, 0) > 0


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
