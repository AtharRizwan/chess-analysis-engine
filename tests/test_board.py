import chess

from chess_analysis_engine.facts.board import (
    best_capture,
    is_recapture,
    material_balance,
    rescues_piece,
    sacrificed_material,
    see,
)


def move(board: chess.Board, san: str) -> chess.Move:
    return board.parse_san(san)


def test_see_even_trade_and_losing_capture():
    board = chess.Board("4k3/8/4p3/3p4/4P3/8/8/4K3 w - - 0 1")
    assert see(board, move(board, "exd5")) == 0  # pawn for pawn
    board = chess.Board("4k3/8/4p3/3p4/4P3/2N5/8/4K3 w - - 0 1")
    assert see(board, move(board, "exd5")) == 100  # the knight backs up the capture
    board = chess.Board("4k3/8/3p4/4p3/8/5N2/8/4K3 w - - 0 1")
    assert see(board, move(board, "Nxe5")) == -200  # knight for pawn


def test_see_respects_pins():
    # The c6 knight is pinned to the king by Bb5, so it can't recapture on e5.
    board = chess.Board("r1bqk2r/ppp2ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1")
    assert see(board, move(board, "Nxe5")) == 100


def test_best_capture_finds_free_material():
    board = chess.Board("4k3/8/8/3n4/8/8/3R4/4K3 w - - 0 1")
    value, capture = best_capture(board, chess.D5)
    assert value == 300
    assert capture == move(board, "Rxd5")


def test_queen_sacrifice_in_the_opera_game():
    board = chess.Board("4kb1r/p2n1ppp/4q3/4p1B1/4P3/1Q6/PPP2PPP/2KR4 w k - 0 16")
    assert sacrificed_material(board, move(board, "Qb8+")) == 900
    # A quiet developing move offers nothing.
    assert sacrificed_material(chess.Board(), chess.Move.from_uci("g1f3")) == 0


def test_only_material_the_move_newly_offers_counts_as_a_sacrifice():
    # 8.Bxd5 gives the bishop for a pawn: if 8...Qxd5, 9.Nf6+ forks king and queen.
    board = chess.Board("r1bqk2r/ppp2p1p/2n3p1/3pp3/1bB1NP2/6Q1/PPPP2PP/R1B1K1NR w KQkq - 0 8")
    assert sacrificed_material(board, move(board, "Bxd5")) == 200
    # White's knight on d5 already hangs to the e6 pawn; a quiet move elsewhere doesn't "offer" it.
    board = chess.Board("4k3/8/4p3/3N4/8/8/PP6/4K3 w - - 0 1")
    assert rescues_piece(board, move(board, "Nc3"))
    assert sacrificed_material(board, move(board, "a3")) == 0
    # King moves never count, even while something else hangs.
    assert sacrificed_material(board, move(board, "Kd2")) == 0
    # Taking a rook while a knight is left hanging: the rook pays for the knight.
    board = chess.Board("4k3/8/8/3n4/8/8/1r6/1R2K3 w - - 0 1")
    assert sacrificed_material(board, move(board, "Rxb2")) == 0


def test_recapture_leaving_an_old_hanging_piece_is_no_sacrifice():
    # 7...Bxc3+ 8.bxc3: White's bishop on h6 was already en prise (g7 pawn), before and after.
    board = chess.Board("rnbqk2r/pppp1ppp/7B/4P3/3PP3/2b2N2/PPP3PP/R2QKB1R w KQkq - 0 8")
    assert sacrificed_material(board, move(board, "bxc3")) == 0


def test_rescuing_an_attacked_piece():
    board = chess.Board("4k3/8/4p3/3N4/8/8/8/4K3 w - - 0 1")  # e6 pawn attacks the d5 knight
    assert rescues_piece(board, move(board, "Nc3"))
    assert not rescues_piece(board, move(board, "Kd2"))


def test_recapture_detection():
    board = chess.Board()
    for san in ["e4", "d5", "exd5"]:
        board.push_san(san)
    assert is_recapture(board, move(board, "Qxd5"))
    assert not is_recapture(board, move(board, "Nf6"))


def test_material_balance():
    board = chess.Board("4k3/8/8/3n4/8/8/3R4/4K3 w - - 0 1")
    assert material_balance(board, chess.WHITE) == 200
