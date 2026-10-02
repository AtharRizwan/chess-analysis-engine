import pytest

from chess_analysis_engine.pgn import PgnError, detect_user_color, read_games

CLOCK_GAME = """[Event "Live Chess"]
[White "Alice"]
[Black "bob42"]
[Result "0-1"]
[TimeControl "180+2"]

1. e4 {[%clk 0:03:01]} 1... e5 {[%clk 0:02:59.5]} 2. Qh5 {[%clk 0:02:58]} 2... Nc6 {[%clk 0:02:50]}
3. Bc4 {[%clk 0:02:50]} 3... Nf6 {[%clk 0:02:45]} 0-1
"""


def test_reads_moves_headers_and_clocks():
    (game,) = read_games(CLOCK_GAME)
    assert game.sans == ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6"]
    assert game.white == "Alice" and game.black == "bob42"
    assert game.time_control == (180.0, 2.0)
    assert game.clocks[:2] == [181.0, 179.5]
    # White: 180 → 181 with +2 increment = 1s; then 181 → 178 = 5s.
    spent = game.time_spent()
    assert spent[0] == pytest.approx(1.0)
    assert spent[2] == pytest.approx(5.0)
    assert spent[3] == pytest.approx(11.5)


def test_detects_the_users_side_case_insensitively():
    (game,) = read_games(CLOCK_GAME)
    assert detect_user_color(game, ["BOB42"]) == "black"
    assert detect_user_color(game, ["someone"]) is None


def test_multiple_games_and_custom_start_position():
    text = CLOCK_GAME + '\n[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"]\n\n1. e4 Kd7 *\n'
    games = read_games(text)
    assert len(games) == 2
    assert games[1].start_fen.startswith("4k3/8/8/8/8/8/4P3/4K3 w")
    assert games[1].clocks == [None, None]
    assert games[1].time_spent() == [None, None]


def test_rejects_variants_and_garbage():
    with pytest.raises(PgnError):
        chess960 = "bqnb1rkr/pp3ppp/3ppn2/2p5/5P2/P2P4/NPP1P1PP/BQ1BNRKR w HFhf - 2 9"
        read_games(f'[Variant "Chess960"]\n[FEN "{chess960}"]\n\n*')
    with pytest.raises(PgnError):
        read_games("")
