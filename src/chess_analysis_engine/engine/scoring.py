"""Turning engine scores into winning chances, expected points and accuracy.

Two curves:
- winning chances (the graph, the "64% → 8%" text) and accuracy use lichess's curve and formulas,
  fitted on human games: https://lichess.org/page/accuracy
- expected points for move *labels* use a flatter curve, fitted to chess.com's Game Review of the
  user's own games: a two-pawn swing in a level position weighs less, and +8 → +12 in a decided one
  weighs more. It is one fixed curve, not adjusted to anyone's rating.
"""

from __future__ import annotations

import math
from statistics import pstdev

from chess_analysis_engine.models import Color, Score

# Slope of lichess's centipawn → winning-chances curve.
K = 0.00368208
# Slope of the curve for move labels (see the module docstring).
LABEL_K = 0.0022
# lichess caps evaluations at ±10 pawns for win% and accuracy.
CP_CEILING = 1000


def cp_to_ep(cp: float, k: float = K) -> float:
    """Expected points (0..1) for the side that is `cp` centipawns ahead (lichess's curve by default)."""
    return 1.0 / (1.0 + math.exp(-k * cp))


def white_ep(score: Score, k: float = LABEL_K) -> float:
    """Expected points for White on the label curve. Mates count as certain wins, unlike in
    `white_win_percent`."""
    if score.result is not None:
        return {"1-0": 1.0, "0-1": 0.0}.get(score.result, 0.5)
    if score.mate is not None:
        return 1.0 if score.mate > 0 else 0.0
    return cp_to_ep(score.cp or 0, k)


def ep_for(score: Score, color: Color, k: float = LABEL_K) -> float:
    """Expected points for `color` on the label curve: what move classification works with."""
    ep = white_ep(score, k)
    return ep if color == "white" else 1.0 - ep


def missed_mate(color: Color, before: Score, after: Score) -> bool:
    """Whether the move lost a forced mate the mover had (`before` is the best line's score, `after` the
    position after the move, both from White's side): the mate is gone, or a short one (mate in 3 or
    less) got longer."""
    sign = 1 if color == "white" else -1
    if before.mate is None or before.mate * sign <= 0:
        return False
    if after.result is not None:
        return after.result != ("1-0" if color == "white" else "0-1")
    if after.mate is None or after.mate * sign <= 0:
        return True
    shortest = before.mate * sign
    return shortest <= 3 and after.mate * sign > shortest - 1


def white_win_percent(score: Score) -> float:
    """White's winning chances in %, capped at ±10 pawns like lichess (mate counts as +10)."""
    if score.result is not None:
        return {"1-0": 100.0, "0-1": 0.0}.get(score.result, 50.0)
    if score.mate is not None:
        cp = CP_CEILING if score.mate > 0 else -CP_CEILING
    else:
        cp = max(-CP_CEILING, min(CP_CEILING, score.cp or 0))
    return 100.0 * cp_to_ep(cp)


def move_accuracy(win_before: float, win_after: float) -> float:
    """lichess move accuracy from the mover's winning chances (in %) before and after."""
    if win_after >= win_before:
        return 100.0
    diff = win_before - win_after
    raw = 103.1668100711649 * math.exp(-0.04354415386753951 * diff) - 3.166924740191411
    return max(0.0, min(100.0, raw + 1.0))  # +1: lichess's bonus for imperfect analysis


def mover_win_percents(white_win_before: float, white_win_after: float, color: Color):
    if color == "white":
        return white_win_before, white_win_after
    return 100.0 - white_win_before, 100.0 - white_win_after


def game_accuracy(white_wins: list[float], first_color: Color = "white") -> dict[Color, float | None]:
    """lichess game accuracy: blend of a volatility-weighted mean and a harmonic mean.

    `white_wins` holds White's win% for every position of the game (moves + 1 entries).
    Moves in calm stretches get less weight than moves in sharp, swingy stretches.
    """
    n_moves = len(white_wins) - 1
    if n_moves < 1:
        return {"white": None, "black": None}
    window = max(2, min(8, n_moves // 10))
    lead = [white_wins[:window]] * max(0, min(window, len(white_wins)) - 2)
    if len(white_wins) >= window:
        sliding = [white_wins[i : i + window] for i in range(len(white_wins) - window + 1)]
    else:
        sliding = [white_wins]
    weights = [max(0.5, min(12.0, pstdev(w))) for w in lead + sliding]

    per_color: dict[Color, list[tuple[float, float]]] = {"white": [], "black": []}
    for i in range(n_moves):
        color: Color = first_color if i % 2 == 0 else ("black" if first_color == "white" else "white")
        before, after = mover_win_percents(white_wins[i], white_wins[i + 1], color)
        per_color[color].append((move_accuracy(before, after), weights[i]))

    result: dict[Color, float | None] = {}
    for color, items in per_color.items():
        if not items:
            result[color] = None
            continue
        weighted = sum(a * w for a, w in items) / sum(w for _, w in items)
        harmonic = len(items) / sum(1.0 / max(1.0, a) for a, _ in items)
        result[color] = (weighted + harmonic) / 2.0
    return result
