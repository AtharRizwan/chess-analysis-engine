"""Motif detectors on small hand-built positions with known winning lines."""

import chess
import pytest

from chess_analysis_engine.facts.lines import Line
from chess_analysis_engine.facts.mates import mate_pattern
from chess_analysis_engine.facts.tactics import detect_motifs, pins


def motifs(fen: str, uci: list[str]) -> dict[str, object]:
    board = chess.Board(fen)
    found = detect_motifs(Line.from_uci(board, uci), board.turn)
    return {m.name: m for m in found}


def test_knight_fork_of_king_and_rook():
    found = motifs("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1", ["b5c7", "e8d7", "c7a8"])
    fork = found["fork"]
    assert fork.ply == 0
    assert set(fork.targets) == {chess.E8, chess.A8}
    assert fork.detail["piece"] == chess.KNIGHT


def test_no_fork_claim_without_payoff():
    # The knight attacks king and rook, but the line never wins the rook.
    assert "fork" not in motifs("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1", ["b5c7", "e8d7"])


def test_pin_wins_the_pinned_queen():
    found = motifs("4k3/8/8/4q3/8/8/3K4/R7 w - - 0 1", ["a1e1", "e5e1", "d2e1"])
    pin = found["pin"]
    assert pin.detail["absolute"] is True
    assert pin.targets == [chess.E5, chess.E8]


def test_pins_finder():
    board = chess.Board("r1bqk2r/ppp2ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1")
    assert (chess.B5, chess.C6, chess.E8, True) in pins(board, chess.BLACK)


def test_pinned_defender_cannot_recapture():
    found = motifs("r1bqk2r/ppp2ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1", ["f3e5", "e8g8"])
    assert found["pin"].detail["use"] == "pinned_defender"


def test_skewer_along_the_rank():
    found = motifs("8/8/8/8/1q2k3/8/8/6KR w - - 0 1", ["h1h4", "e4d3", "h4b4"])
    skewer = found["skewer"]
    assert skewer.targets == [chess.E4, chess.B4]


def test_discovered_attack_with_check():
    found = motifs("3k4/6q1/8/8/3N4/8/1B6/4K3 w - - 0 1", ["d4c6", "d8d7", "b2g7"])
    assert found["discovered_attack"].targets == [chess.G7]


def test_double_check_then_fork():
    found = motifs("4k3/7q/8/8/4N3/8/8/K3R3 w - - 0 1", ["e4f6", "e8f8", "f6h7"])
    assert "double_check" in found
    assert "fork" in found
    ordered = detect_motifs(
        Line.from_uci(chess.Board("4k3/7q/8/8/4N3/8/8/K3R3 w - - 0 1"), ["e4f6", "e8f8", "f6h7"]), chess.WHITE
    )
    assert ordered[0].name == "double_check"


def test_hanging_piece_is_just_taken():
    found = motifs("4k3/8/8/3n4/8/8/3R4/4K3 w - - 0 1", ["d2d5"])
    assert found["hanging_piece"].detail == {"victim": chess.KNIGHT, "defended": False}


def test_trapped_bishop_on_a7():
    found = motifs("2k5/Bpp5/8/8/8/8/8/6K1 b - - 0 1", ["b7b6", "g1f2", "c8b7", "f2e3", "b7a7"])
    assert found["trapped_piece"].targets == [chess.A7]


@pytest.mark.parametrize(
    ("fen", "uci", "pattern"),
    [
        ("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", ["d1d8"], "back_rank_mate"),
        ("6rk/6pp/8/6N1/8/8/8/6K1 w - - 0 1", ["g5f7"], "smothered_mate"),
    ],
)
def test_mate_patterns(fen, uci, pattern):
    board = chess.Board(fen)
    line = Line.from_uci(board, uci)
    assert mate_pattern(line.end) == pattern
    mate = motifs(fen, uci)["mate"]
    assert mate.detail == {"pattern": pattern, "mate_in": 1}


def test_settle_point_cuts_after_the_material_is_won():
    board = chess.Board("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1")
    line = Line.from_uci(board, ["b5c7", "e8d7", "c7a8", "d7c8", "e1d2", "c8b8"])
    assert line.settle_point() == 3
    assert line.trimmed().sans == ["Nc7+", "Kd7", "Nxa8", "Kc8"]
    assert line.net_material(chess.WHITE, 3) == 500
