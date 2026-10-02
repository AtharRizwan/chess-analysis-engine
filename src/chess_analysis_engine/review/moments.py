"""Game phases and the key moments worth studying first."""

from __future__ import annotations

import chess

from chess_analysis_engine.models import Color, MoveReview, Phase

_PIECES = (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)


def game_phase(board: chess.Board) -> Phase:
    """lichess-style divider: few pieces left → endgame; thinned back ranks → middlegame."""
    majors_minors = sum(len(board.pieces(pt, c)) for pt in _PIECES for c in chess.COLORS)
    if majors_minors <= 6:
        return "endgame"
    white_back = len(chess.SquareSet(board.occupied_co[chess.WHITE] & chess.BB_RANK_1))
    black_back = len(chess.SquareSet(board.occupied_co[chess.BLACK] & chess.BB_RANK_8))
    if majors_minors <= 10 or white_back < 4 or black_back < 4:
        return "middlegame"
    return "opening"


_DIFFICULTY_WEIGHT = {"easy": 1.5, "medium": 1.0, "hard": 0.6, None: 1.0}
_POSITIVE = {"brilliant", "great"}
_NEGATIVE = {"blunder", "mistake", "miss"}


def key_moments(moves: list[MoveReview], user_color: Color | None, per_side: int = 4) -> list[int]:
    """Plies most worth studying: costly mistakes (easy-to-find fixes first) and great finds.

    With a known user side, only that side's moments are picked.
    """
    sides: list[Color] = [user_color] if user_color else ["white", "black"]
    chosen: list[int] = []
    for side in sides:
        mistakes = [m for m in moves if m.color == side and m.classification in _NEGATIVE]
        mistakes.sort(key=lambda m: -m.ep_loss * _DIFFICULTY_WEIGHT[m.difficulty])
        good = [m for m in moves if m.color == side and m.classification in _POSITIVE]
        good.sort(key=lambda m: m.classification != "brilliant")
        chosen += [m.ply for m in mistakes[:per_side]] + [m.ply for m in good[:2]]
    return sorted(set(chosen))
