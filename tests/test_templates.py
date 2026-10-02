from chess_analysis_engine.explain.templates import Voice, and_join, captures, outcome, winnings
from chess_analysis_engine.models import LineRef

# 1. e4 d5 2. exd5 Qxd5 3. Nc3 Qa5: an even pawn trade.
TRADE = LineRef(
    start_fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    uci=["e2e4", "d7d5", "e4d5", "d8d5", "b1c3", "d5a5"],
    san=["e4", "d5", "exd5", "Qxd5", "Nc3", "Qa5"],
)
# A knight wins a rook after a fork.
FORK = LineRef(
    start_fen="r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1", uci=["b5c7", "e8d7", "c7a8"], san=["Nc7+", "Kd7", "Nxa8"]
)


def test_voice_with_known_user():
    v = Voice("white")
    assert v.who("white") == "you" and v.who("black") == "your opponent"
    assert v.piece({"color": "black", "piece": "rook", "square": "a8"}) == "their rook on a8"
    pawns = [
        {"color": "white", "piece": "pawn", "square": "b2"},
        {"color": "white", "piece": "pawn", "square": "f2"},
    ]
    assert v.pieces(pawns) == "your pawns on b2 and f2"


def test_voice_without_user_names_colors():
    v = Voice(None)
    assert v.who("black") == "Black"
    assert v.piece({"color": "white", "piece": "queen", "square": "d1"}) == "White's queen on d1"


def test_even_trades_cancel_out():
    assert captures(TRADE, "white") == ([], [])
    assert outcome(TRADE, "white", Voice("black")) == ""


def test_outcome_and_winnings_wording():
    assert outcome(FORK, "white", Voice("black")) == "you lose a rook"
    assert outcome(FORK, "white", Voice(None)) == "Black loses a rook"
    assert winnings(FORK, "white", Voice("white")) == "you would have won a rook"
    assert winnings(FORK, "white", Voice("white"), would=False) == "you win a rook"


def test_and_join():
    assert and_join(["a"]) == "a"
    assert and_join(["a", "b", "c"]) == "a, b and c"
