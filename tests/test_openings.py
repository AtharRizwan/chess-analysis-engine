import chess

from chess_analysis_engine.pgn import read_games
from chess_analysis_engine.review.openings import identify, load_book


def test_names_the_italian_game():
    board = chess.Board()
    for san in ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]:
        board.push_san(san)
    opening = load_book().name_of(board)
    assert opening is not None
    assert opening.eco == "C50"
    assert "Italian" in opening.name


def test_book_moves_stop_at_the_first_novelty(fixtures):
    (game,) = read_games((fixtures / "opera_game.pgn").read_text())
    flags, opening, left_book_ply = identify(game.boards()[1:], standard_start=True)
    assert opening is not None and opening.eco == "C41"  # Philidor Defense
    assert left_book_ply == 8  # 4...Bxf3
    assert all(flags[:7]) and not any(flags[7:])


def test_no_book_for_custom_start_positions():
    boards = [chess.Board("4k3/8/8/8/8/8/4P3/4K3 b - - 0 1")]
    assert identify(boards, standard_start=False) == ([False], None, None)
