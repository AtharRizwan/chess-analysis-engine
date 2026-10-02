"""Turning engine scores into winning chances, expected points and accuracy.

The curve and the accuracy formulas are lichess's, which were fitted on human games:
https://lichess.org/page/accuracy
"""

from __future__ import annotations

import math
from statistics import pstdev

from chess_analysis_engine.models import Color, Score

# Slope of lichess's centipawn → winning-chances curve.
K = 0.00368208
# lichess caps evaluations at ±10 pawns for win% and accuracy.
CP_CEILING = 1000


def cp_to_ep(cp: float) -> float:
    """Expected points (0..1) for the side that is `cp` centipawns ahead."""
    return 1.0 / (1.0 + math.exp(-K * cp))


def white_ep(score: Score) -> float:
    """Expected points for White. Mates count as certain wins, unlike in `white_win_percent`."""
    if score.result is not None:
        return {"1-0": 1.0, "0-1": 0.0}.get(score.result, 0.5)
    if score.mate is not None:
        return 1.0 if score.mate > 0 else 0.0
    return cp_to_ep(score.cp or 0)


def ep_for(score: Score, color: Color) -> float:
    ep = white_ep(score)
    return ep if color == "white" else 1.0 - ep


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
