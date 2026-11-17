from __future__ import annotations

from pathlib import Path

import chess
import pytest

from chess_analysis_engine.config import find_stockfish
from chess_analysis_engine.engine.pool import EnginePool
from chess_analysis_engine.models import (
    EngineLine,
    Explanation,
    ExplanationSection,
    Fact,
    LineRef,
    MoveReview,
    Score,
)
from chess_analysis_engine.storage.db import Database

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture(scope="session")
def pool():
    """Two single-threaded engines; engine tests are skipped when Stockfish is missing."""
    path = find_stockfish()
    if not path:
        pytest.skip("Stockfish not installed")
    with EnginePool(path, size=2, hash_mb=32) as engines:
        yield engines


def fen_after(*sans: str) -> str:
    """The position after these moves from the start."""
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board.fen()


@pytest.fixture
def move() -> MoveReview:
    """3...Nf6?? walking into 4. Qxf7# (Black is the user)."""
    before = fen_after("e4", "e5", "Bc4", "Nc6", "Qh5")
    after = fen_after("e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6")
    mate_line = LineRef(start_fen=after, uci=["h5f7"], san=["Qxf7#"])
    return MoveReview(
        ply=6,
        move_number=3,
        color="black",
        san="Nf6",
        uci="g8f6",
        fen_before=before,
        fen_after=after,
        eval_before=Score(cp=30),
        eval_after=Score(mate=1),
        win_before=55.0,
        win_after=100.0,
        ep_before=0.47,
        ep_after=0.0,
        ep_loss=0.47,
        accuracy=0.0,
        classification="blunder",
        best=EngineLine(
            uci=["g7g6", "h5f3", "g8f6"], san=["g6", "Qf3", "Nf6"], score=Score(cp=-20), depth=18
        ),
        refutation=EngineLine(uci=["h5f7"], san=["Qxf7#"], score=Score(mate=1), depth=18),
        facts=[
            Fact(
                id="f1",
                kind="allows_mate",
                actor="white",
                squares=["f7"],
                line=mate_line,
                data={"mate_in": 1},
            ),
            Fact(id="f2", kind="best_defends", actor="black", squares=["f7"]),
        ],
        explanation=Explanation(
            headline="3...Nf6?? allows 4. Qxf7#, checkmate.",
            sections=[
                ExplanationSection(
                    title="What went wrong", text="It allows mate.", fact_ids=["f1"], line=mate_line
                ),
                ExplanationSection(title="Better was 3...g6", text="It blocks the queen."),
            ],
            lesson="Check every capture on the squares next to your king.",
            hints=["There's a threat against f7."],
            focus="f7",
        ),
    )
