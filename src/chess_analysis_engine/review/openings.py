"""Opening names and "book" detection from the lichess chess-openings dataset (CC0)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache

import chess

from chess_analysis_engine.config import RESOURCES_DIR
from chess_analysis_engine.models import OpeningRef

OPENINGS_DIR = RESOURCES_DIR / "openings"


@dataclass(frozen=True)
class OpeningBook:
    named: dict[str, OpeningRef]  # EPD of the final position of a named line → its name
    book: frozenset[str]  # EPD of every position along every named line

    def name_of(self, board: chess.Board) -> OpeningRef | None:
        return self.named.get(board.epd())

    def is_book(self, board: chess.Board) -> bool:
        return board.epd() in self.book


def _pgn_moves(movetext: str) -> list[str]:
    return [tok for tok in movetext.split() if not tok[0].isdigit()]


@lru_cache(maxsize=1)
def load_book() -> OpeningBook:
    named: dict[str, OpeningRef] = {}
    book: set[str] = set()
    for path in sorted(OPENINGS_DIR.glob("*.tsv")):
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                board = chess.Board()
                for san in _pgn_moves(row["pgn"]):
                    board.push_san(san)
                    book.add(board.epd())
                named.setdefault(board.epd(), OpeningRef(eco=row["eco"], name=row["name"]))
    return OpeningBook(named=named, book=frozenset(book))


def identify(
    boards_after_moves: list[chess.Board], standard_start: bool
) -> tuple[list[bool], OpeningRef | None, int | None]:
    """Book flags per ply, the most specific opening name, and the first ply out of book.

    A move counts as "book" only while every move before it was also book.
    """
    if not standard_start:
        return [False] * len(boards_after_moves), None, None
    opening_book = load_book()
    flags: list[bool] = []
    opening: OpeningRef | None = None
    in_book = True
    left_book_ply: int | None = None
    for ply, board in enumerate(boards_after_moves, start=1):
        in_book = in_book and opening_book.is_book(board)
        flags.append(in_book)
        if not in_book and left_book_ply is None:
            left_book_ply = ply
        # Transpositions back into a named position still name the opening.
        if ply <= 40 and (named := opening_book.name_of(board)) is not None:
            opening = named
    return flags, opening, left_book_ply
