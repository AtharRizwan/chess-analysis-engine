"""Move classification (Best … Blunder, plus Book, Forced, Great, Brilliant and Miss).

Thresholds are on expected points (0..1) lost by the mover, like chess.com's published table.
They are deliberately fixed — not adjusted to the player's rating.
"""

from __future__ import annotations

from dataclasses import dataclass

from chess_analysis_engine.models import Classification

EXCELLENT = 0.02
GOOD = 0.05
INACCURACY = 0.10
MISTAKE = 0.20

# "Great": the best move, and the next best is at least this much worse (an only-move).
ONLY_MOVE_GAP = 0.10
# "Brilliant": a sound sacrifice of at least this much material (an exchange or more)...
BRILLIANT_MIN_SACRIFICE = 200
# ...that doesn't leave you worse...
BRILLIANT_MIN_EP_AFTER = 0.45
# ...in a position where the quiet alternatives weren't already completely winning.
BRILLIANT_MAX_ALTERNATIVE_EP = 0.92
# "Miss": giving back an opponent's gift without falling below where you stood before it.
MISS_TOLERANCE = 0.02


@dataclass(frozen=True)
class MoveContext:
    played_uci: str
    best_uci: str | None
    ep_before: float  # mover's expected points with best play
    ep_after: float  # mover's expected points after the played move
    second_best_ep: float | None  # mover's expected points after the second-best move
    legal_moves: int
    book: bool = False
    sacrifice: int = 0
    is_recapture: bool = False
    in_check: bool = False
    delivers_mate: bool = False
    opponent_prev_loss: float | None = None  # what the opponent's previous move cost them
    ep_before_opponent_error: float | None = None  # mover's EP before that previous move

    @property
    def loss(self) -> float:
        return max(0.0, self.ep_before - self.ep_after)

    @property
    def is_best(self) -> bool:
        return self.best_uci is not None and self.played_uci == self.best_uci


def is_great(c: MoveContext) -> bool:
    if not c.is_best or c.second_best_ep is None:
        return False
    if c.delivers_mate or c.is_recapture or (c.in_check and c.legal_moves <= 3):
        return False  # mates, obvious recaptures and forced king walks aren't "great finds"
    return c.ep_before - c.second_best_ep >= ONLY_MOVE_GAP


def is_brilliant(c: MoveContext) -> bool:
    if not (c.is_best or c.loss <= EXCELLENT):
        return False
    if c.sacrifice < BRILLIANT_MIN_SACRIFICE or c.ep_after < BRILLIANT_MIN_EP_AFTER:
        return False
    return c.second_best_ep is None or c.second_best_ep < BRILLIANT_MAX_ALTERNATIVE_EP


def is_miss(c: MoveContext) -> bool:
    if c.opponent_prev_loss is None or c.opponent_prev_loss <= INACCURACY:
        return False
    if c.ep_before_opponent_error is None:
        return False
    return c.ep_after >= c.ep_before_opponent_error - MISS_TOLERANCE


def classify(c: MoveContext) -> Classification:
    if c.legal_moves == 1:
        return "forced"
    if c.book:
        return "book"
    if is_brilliant(c):
        return "brilliant"
    if c.is_best:
        return "great" if is_great(c) else "best"
    loss = c.loss
    if loss <= EXCELLENT:
        return "excellent"
    if loss <= GOOD:
        return "good"
    if loss <= INACCURACY:
        return "inaccuracy"
    if is_miss(c):
        return "miss"
    if loss <= MISTAKE:
        return "mistake"
    return "blunder"


BAD = {"inaccuracy", "mistake", "miss", "blunder"}
SERIOUS = {"mistake", "miss", "blunder"}
