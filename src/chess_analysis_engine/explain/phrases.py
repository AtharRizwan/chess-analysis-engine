"""Small text helpers: move numbering, lines, and evaluations in plain language."""

from __future__ import annotations

import chess

from chess_analysis_engine.models import Color, Score

CLASSIFICATION_LABELS = {
    "brilliant": "Brilliant",
    "great": "Great move",
    "best": "Best",
    "excellent": "Excellent",
    "good": "Good",
    "book": "Book",
    "forced": "Forced",
    "inaccuracy": "Inaccuracy",
    "mistake": "Mistake",
    "miss": "Miss",
    "blunder": "Blunder",
}
CLASSIFICATION_SYMBOLS = {
    "brilliant": "!!",
    "great": "!",
    "inaccuracy": "?!",
    "mistake": "?",
    "miss": "?",
    "blunder": "??",
}


def move_label(move_number: int, color: Color, san: str) -> str:
    """'14. Bd3' for White, '14...Qxb2' for Black."""
    return f"{move_number}. {san}" if color == "white" else f"{move_number}...{san}"


def numbered_line(fen: str, sans: list[str], max_plies: int | None = None) -> str:
    """'14. Qd2 Qxb2 15. Rb1' from a start position and a SAN list."""
    board = chess.Board(fen)
    number, white = board.fullmove_number, board.turn == chess.WHITE
    parts: list[str] = []
    for k, san in enumerate(sans[:max_plies]):
        if white:
            parts.append(f"{number}. {san}")
        else:
            parts.append(f"{number}...{san}" if k == 0 else san)
            number += 1
        white = not white
    return " ".join(parts)


def percent(value: float) -> str:
    return f"{value:.0f}%"


def mover_win(win_white: float, color: Color) -> float:
    return win_white if color == "white" else 100.0 - win_white


def describe_eval(score: Score, color: Color) -> str:
    """How the position looks for `color`, in words."""
    if score.result is not None:
        if score.result == "1/2-1/2":
            return "a draw"
        won = (score.result == "1-0") == (color == "white")
        return "game over — you won" if won else "game over — you lost"
    if score.mate is not None:
        mating = (score.mate > 0) == (color == "white")
        n = abs(score.mate)
        return f"forced mate in {n} for you" if mating else f"forced mate in {n} against you"
    cp = (score.cp or 0) * (1 if color == "white" else -1)
    magnitude = abs(cp)
    if magnitude < 50:
        return "about equal"
    if magnitude < 120:
        word = "slightly better"
    elif magnitude < 300:
        word = "clearly better"
    elif magnitude < 700:
        word = "winning"
    else:
        word = "completely winning"
    return f"you are {word}" if cp > 0 else f"your opponent is {word}"
