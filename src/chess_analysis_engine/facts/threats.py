"""Threats: what would a side do if it could move twice?

We let the side that is *not* to move play again (a "null move" by the side to move) and ask
the engine for its best move. If that wins material or mates, it was a threat — the classic
"what does my opponent want?" question that most blunders skip.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_analysis_engine.engine.pool import EnginePool
from chess_analysis_engine.facts.board import best_capture, captures_on, see
from chess_analysis_engine.facts.lines import Line
from chess_analysis_engine.facts.tactics import Motif, detect_motifs

MIN_THREAT_GAIN = 100  # a pawn
THREAT_DEPTH = 12


@dataclass
class Threat:
    side: chess.Color  # who threatens
    move: chess.Move
    san: str
    line: Line  # from the null-move position, trimmed to where it settles
    gain: int  # material the threat wins, in centipawns
    mate_in: int | None
    motifs: list[Motif]
    target: chess.Square | None  # what is threatened: first square captured on, or the king

    @property
    def main_motif(self) -> Motif | None:
        return self.motifs[0] if self.motifs else None


def null_move_board(board: chess.Board) -> chess.Board | None:
    """`board` with the other side to move, or None when that would be illegal (in check)."""
    if board.is_check():
        return None
    flipped = board.copy(stack=False)
    flipped.push(chess.Move.null())
    flipped = chess.Board(flipped.fen())
    return flipped if flipped.is_valid() else None


def in_exchange(board: chess.Board) -> bool:
    """The opponent just captured and we can take back: we're mid-trade, not facing a threat."""
    if not board.move_stack:
        return False
    last = board.peek()
    board.pop()
    try:
        was_capture = board.is_capture(last)
    finally:
        board.push(last)
    if not was_capture:
        return False
    return any(see(board, m) >= 0 for m in captures_on(board, last.to_square))


def find_threat(pool: EnginePool, board: chess.Board, depth: int = THREAT_DEPTH) -> Threat | None:
    """The threat held by the side that is NOT to move in `board`, if any."""
    if board.is_game_over() or in_exchange(board):
        return None
    flipped = null_move_board(board)
    if flipped is None:
        return None
    analysis = pool.analyse(flipped, depth=depth, multipv=1)
    if analysis.best is None:
        return None
    side = flipped.turn
    line = Line.from_uci(flipped, analysis.best.uci)
    if not line.moves:
        return None
    mate = analysis.score.mate
    mate_in = abs(mate) if mate is not None and (mate > 0) == (side == chess.WHITE) else None
    gain = line.net_material(side, line.settle_point(side))
    if mate_in is None and gain < MIN_THREAT_GAIN:
        return None
    trimmed = line.trimmed(side)
    return Threat(
        side=side,
        move=line.moves[0],
        san=line.sans[0],
        line=trimmed,
        gain=gain,
        mate_in=mate_in,
        motifs=detect_motifs(trimmed, side),
        target=_target(trimmed, side, mate_in is not None),
    )


def _target(line: Line, side: chess.Color, mating: bool) -> chess.Square | None:
    if mating:
        return line.start.king(not side)
    for k, move in enumerate(line.moves):
        board = line.boards[k]
        if board.turn == side and board.is_capture(move):
            return move.to_square
    return None


def same_threat(threat: Threat, board_after: chess.Board, reply_uci: list[str]) -> bool:
    """Does the opponent's actual continuation carry out `threat` (within their first two moves)?"""
    if not reply_uci:
        return False
    line = Line.from_uci(board_after, reply_uci[:4])
    for k in range(0, len(line), 2):  # the opponent moves at even plies
        move, board = line.moves[k], line.boards[k]
        if move == threat.move:
            return True
        if threat.target is not None and board.is_capture(move) and move.to_square == threat.target:
            return True
    return threat.mate_in is not None and Line.from_uci(board_after, reply_uci).end.is_checkmate()


def newly_winnable(board: chess.Board, move: chess.Move) -> list[chess.Square]:
    """Enemy pieces that `move` (by the side to move) makes winnable: before it, capturing them
    lost material or wasn't possible; after it, a capture wins material. This is the plain "double
    attack" idea, including attacks uncovered on other lines."""
    actor = board.turn
    before = board.copy(stack=False)
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return []
    probe = after.copy(stack=False)
    probe.turn = actor
    probe.ep_square = None
    found = []
    for square in chess.SquareSet(after.occupied_co[not actor]):
        if after.piece_type_at(square) == chess.KING:
            continue
        if best_capture(probe, square)[0] > 0 and best_capture(before, square)[0] <= 0:
            found.append(square)
    return found


def parry_method(board: chess.Board, move: chess.Move, threat: Threat) -> str | None:
    """How `move` (by the side to move in `board`) deals with `threat`, in a word."""
    mover = board.turn
    target = threat.target
    attacker = threat.move.from_square
    after = board.copy(stack=False)
    after.push(move)
    if threat.mate_in is not None:
        king = board.king(mover)
        if king is not None and len(_escape_squares(after, mover)) > len(_escape_squares(board, mover)):
            return "luft"
    if target is not None and target != board.king(mover) and move.from_square == target:
        return "moves_away"
    if move.to_square == attacker and board.is_capture(move):
        return "captures_attacker"
    if board.gives_check(move):
        return "check"
    if target is not None and move.to_square in chess.SquareSet(chess.between(attacker, target)):
        return "blocks"
    if target is not None and len(after.attackers(mover, target)) > len(board.attackers(mover, target)):
        return "defends"
    key = threat.move.to_square
    if after.is_attacked_by(mover, key) and not board.is_attacked_by(mover, key):
        return "covers_square"
    return None


def _escape_squares(board: chess.Board, color: chess.Color) -> list[chess.Square]:
    king = board.king(color)
    if king is None:
        return []
    return [
        sq
        for sq in chess.SquareSet(chess.BB_KING_ATTACKS[king])
        if board.color_at(sq) != color and not board.is_attacked_by(not color, sq)
    ]
