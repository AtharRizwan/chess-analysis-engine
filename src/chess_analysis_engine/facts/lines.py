"""Replaying engine lines with material bookkeeping, and finding where a line "settles".

Engine principal variations run on long after the point of a tactic. For explanations we
cut a line where its material outcome is settled: after the last capture or promotion of the
sequence, at a position where the side to move has no winning capture and isn't in check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from chess_analysis_engine.facts.board import material_balance, winning_captures
from chess_analysis_engine.models import LineRef

MAX_PLIES = 14
QUIET_TAIL = 1  # show one calm move after the material is settled


@dataclass
class Line:
    """A sequence of moves from a start position, replayed once."""

    start: chess.Board
    moves: list[chess.Move]
    boards: list[chess.Board] = field(default_factory=list)  # boards[k]: before moves[k]; last = end
    sans: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        board = self.start.copy(stack=False)
        self.boards = [board.copy(stack=False)]
        legal: list[chess.Move] = []
        for move in self.moves:
            if not board.is_legal(move):
                break
            self.sans.append(board.san(move))
            board.push(move)
            legal.append(move)
            self.boards.append(board.copy(stack=False))
        self.moves = legal

    @classmethod
    def from_uci(cls, start: chess.Board, uci: list[str]) -> Line:
        return cls(start, [chess.Move.from_uci(u) for u in uci])

    def __len__(self) -> int:
        return len(self.moves)

    @property
    def end(self) -> chess.Board:
        return self.boards[-1]

    def mover(self, ply: int) -> chess.Color:
        return self.boards[ply].turn

    def balance(self, ply: int, color: chess.Color) -> int:
        """Material balance for `color` in the position before move `ply` (or at the end)."""
        return material_balance(self.boards[ply], color)

    def net_material(self, color: chess.Color, upto: int | None = None) -> int:
        """Material `color` gains from the start of the line to position `upto` (default: end)."""
        upto = len(self) if upto is None else upto
        return self.balance(upto, color) - self.balance(0, color)

    def ends_in_mate(self, upto: int | None = None) -> bool:
        upto = len(self) if upto is None else upto
        return self.boards[upto].is_checkmate()

    def settle_point(self, actor: chess.Color | None = None, max_plies: int = MAX_PLIES) -> int:
        """Number of plies after which the material outcome of the line is settled for `actor`
        (default: the side to move at the start).

        Only calm positions count (no check, no winning capture pending): material in the middle
        of an exchange means nothing. We settle at the first calm position where the actor's gain
        reaches its best calm value. A tactic often starts with an even trade and only the
        follow-up (a fork, a skewer) wins, so the best value, not the first change, decides.
        """
        limit = min(len(self), max_plies)
        for k in range(1, limit + 1):
            if _finished(self.boards[k]):
                return k
        actor = self.boards[0].turn if actor is None else actor
        calm = [k for k in range(1, limit + 1) if _calm(self.boards[k])]
        if not calm:
            return limit
        gains = {k: self.net_material(actor, k) for k in calm}
        best = max(gains.values())
        if best <= 0:
            # Lines often end on the winning capture itself; count it once pending recaptures are
            # settled. Otherwise nothing is won: stop at the last calm position, never mid-exchange.
            return limit if self._end_gain(actor, limit) > 0 else calm[-1]
        return min(k for k in calm if gains[k] == best)

    def _end_gain(self, actor: chess.Color, k: int) -> int:
        """Material gained at ply `k`, assuming the best pending capture is then made."""
        gain = self.net_material(actor, k)
        pending = winning_captures(self.boards[k])
        if pending:
            value = pending[0][0]
            gain += value if self.boards[k].turn == actor else -value
        return gain

    def trimmed(
        self, actor: chess.Color | None = None, max_plies: int = MAX_PLIES, tail: int = QUIET_TAIL
    ) -> Line:
        """The line cut just after it settles (plus a calm move for context).

        Never cut in the middle of an exchange: if a winning capture is still pending at the end
        (the engine's line stopped after a capture, before the recapture), back up.
        """
        stop = self.settle_point(actor, max_plies)
        # Add a calm move for context, but never a capture: it would change the material count.
        for _ in range(tail):
            if (
                stop >= len(self)
                or _finished(self.boards[stop])
                or self.boards[stop].is_capture(self.moves[stop])
            ):
                break
            stop += 1
        while stop > 1 and not _finished(self.boards[stop]) and winning_captures(self.boards[stop]):
            stop -= 1
        return Line(self.start, self.moves[:stop])

    def ref(self, upto: int | None = None) -> LineRef:
        upto = len(self) if upto is None else upto
        return LineRef(
            start_fen=self.start.fen(),
            uci=[m.uci() for m in self.moves[:upto]],
            san=self.sans[:upto],
        )


def _calm(board: chess.Board) -> bool:
    return not board.is_check() and not winning_captures(board)


def _finished(board: chess.Board) -> bool:
    # Only mate and stalemate end a line; "insufficient material" positions are still worth showing.
    return board.is_checkmate() or board.is_stalemate()


def prepend(board: chess.Board, move: chess.Move, continuation: list[str]) -> Line:
    """The line starting with `move` from `board`, followed by an engine continuation."""
    return Line(board, [move, *(chess.Move.from_uci(u) for u in continuation)])
