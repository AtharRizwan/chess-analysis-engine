"""Move classification (Best … Blunder, plus Book, Forced, Great, Brilliant and Miss).

Thresholds are on expected points (0..1) lost by the mover, like chess.com's published table, on the
label curve in `engine.scoring` (fitted to chess.com's reviews). They are deliberately fixed — not
adjusted to the player's rating.
"""

from __future__ import annotations

from dataclasses import dataclass

from chess_analysis_engine.models import Classification

EXCELLENT = 0.02
GOOD = 0.04  # chess.com's table says 0.05; on our label curve 0.04 matches its reviews best
INACCURACY = 0.10
MISTAKE = 0.20

# "Great" is either the best move right after the opponent's error that cost them at least this much
# (finding the punishment, like chess.com's "great")...
GREAT_PUNISH_LOSS = 0.15
# ...or a hard only-move: the best move, and the next best is at least this much worse...
ONLY_MOVE_GAP = 0.10
# ...found while the game was still in the balance (an only-move that merely keeps a won game won
# isn't a great find).
GREAT_MAX_EP_BEFORE = 0.90
# "Brilliant": a sound sacrifice of at least this much material (an exchange or more)...
BRILLIANT_MIN_SACRIFICE = 200
# ...that doesn't leave you worse...
BRILLIANT_MIN_EP_AFTER = 0.45
# ...in a position where the quiet alternatives weren't already completely winning...
BRILLIANT_MAX_ALTERNATIVE_EP = 0.92
# ...and that is clearly better than all of them (if a quiet move does about as well, the
# sacrifice wasn't needed).
BRILLIANT_MIN_GAIN = 0.05
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
    takes_material: bool = False  # a capture that wins or keeps material (SEE >= 0)
    rescues_piece: bool = False  # the moved piece was en prise before the move
    in_check: bool = False
    delivers_mate: bool = False
    missed_mate: bool = False  # a forced mate was there and the move lost it (or made a short one longer)
    opponent_prev_loss: float | None = None  # what the opponent's previous move cost them
    ep_before_opponent_error: float | None = None  # mover's EP before that previous move

    @property
    def loss(self) -> float:
        return max(0.0, self.ep_before - self.ep_after)

    @property
    def is_best(self) -> bool:
        return self.best_uci is not None and self.played_uci == self.best_uci


def is_great(c: MoveContext) -> bool:
    """The best move that punishes the opponent's error (their last move cost them a real chunk), or
    a hard-to-find only-move: everything else clearly worse, and not one of the obvious only-moves
    (taking material, recapturing, rescuing an attacked piece, getting out of check, mating) nor one
    that just keeps an already won game won."""
    if not c.is_best:
        return False
    if c.opponent_prev_loss is not None and c.opponent_prev_loss >= GREAT_PUNISH_LOSS:
        return True
    if c.second_best_ep is None:
        return False
    if c.delivers_mate or c.is_recapture or c.takes_material or c.rescues_piece or c.in_check:
        return False
    if c.ep_before >= GREAT_MAX_EP_BEFORE:
        return False
    return c.ep_before - c.second_best_ep >= ONLY_MOVE_GAP


def is_brilliant(c: MoveContext) -> bool:
    """A sound sacrifice that was needed: the engine's move, it puts real material on offer (see
    `sacrificed_material`), you're not worse after it, and every quieter alternative is clearly worse
    and not already completely winning."""
    if not c.is_best or c.sacrifice < BRILLIANT_MIN_SACRIFICE or c.ep_after < BRILLIANT_MIN_EP_AFTER:
        return False
    if c.second_best_ep is None:
        return True
    return (
        c.second_best_ep < BRILLIANT_MAX_ALTERNATIVE_EP
        and c.ep_before - c.second_best_ep >= BRILLIANT_MIN_GAIN
    )


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
    if c.missed_mate and loss <= MISTAKE:
        return "miss"  # e.g. mate in 1 on the board, and the move "only" keeps a winning position
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
