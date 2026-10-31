import chess

from chess_analysis_engine.engine.uci import terminal_score
from chess_analysis_engine.explain.templates import build_explanation
from chess_analysis_engine.facts.extract import MoveInput, explain_move
from chess_analysis_engine.models import Classification, EngineLine, MoveReview, PositionEval, Score

# 1. e4 e5, then the knights shuffle: the position after 1...e5 comes back after 3...Ng8 and 5...Ng8.
SHUFFLE = ["e4", "e5", "Nf3", "Nf6", "Ng1", "Ng8", "Nf3", "Nf6", "Ng1", "Ng8"]
DRAW = Score(result="1/2-1/2")


def played(plies: int) -> chess.Board:
    board = chess.Board()
    for san in SHUFFLE[:plies]:
        board.push_san(san)
    return board


def line(board: chess.Board, uci: list[str], score: Score) -> EngineLine:
    b = board.copy(stack=False)
    san = []
    for u in uci:
        move = chess.Move.from_uci(u)
        san.append(b.san(move))
        b.push(move)
    return EngineLine(uci=uci, san=san, score=score, depth=18)


def review(board: chess.Board, before: PositionEval, after: PositionEval, classification: Classification):
    """Facts and the written explanation for the next move of SHUFFLE."""
    move = board.parse_san(SHUFFLE[len(board.move_stack)])
    facts = explain_move(
        MoveInput(board=board, move=move, before=before, after=after, classification=classification)
    )
    after_board = board.copy(stack=False)
    after_board.push(move)
    bad = classification == "blunder"
    m = MoveReview(
        ply=len(board.move_stack) + 1,
        move_number=board.fullmove_number,
        color="white" if board.turn == chess.WHITE else "black",
        san=board.san(move),
        uci=move.uci(),
        fen_before=board.fen(),
        fen_after=after_board.fen(),
        eval_before=before.score,
        eval_after=after.score,
        win_before=90.0 if bad else 50.0,
        win_after=50.0,
        ep_before=0.9 if bad else 0.5,
        ep_after=0.5,
        ep_loss=0.4 if bad else 0.0,
        accuracy=10.0 if bad else 100.0,
        classification=classification,
        best=before.best,
        refutation=after.best,
        alternatives=before.lines,
        phase="opening",
    )
    return facts.facts, m


def test_threefold_repetition_ends_the_game():
    assert terminal_score(played(10)) == DRAW
    assert terminal_score(played(6)) is None  # only the second time


def test_move_that_repeats_a_third_time():
    board = played(9)
    before = PositionEval(fen=board.fen(), score=Score(cp=0), lines=[line(board, ["f6g8"], Score(cp=0))])
    facts, m = review(board, before, PositionEval(fen=board.fen(), score=DRAW), "best")
    (fact,) = [f for f in facts if f.kind == "repetition"]
    assert fact.actor == "black"
    assert fact.data == {"move": "5...Ng8", "earlier": ["1...e5", "3...Ng8"]}

    explanation = build_explanation(m, facts, "black")
    assert explanation.headline == "Draws by repetition"
    assert explanation.sections[0].text == (
        "5...Ng8 repeats the position for the third time (after 1...e5 and 3...Ng8), "
        "so the game is drawn by repetition."
    )


def test_move_that_lets_the_opponent_repeat():
    board = played(8)
    before = PositionEval(fen=board.fen(), score=Score(cp=500), lines=[line(board, ["b1c3"], Score(cp=500))])
    after_board = played(9)
    after = PositionEval(
        fen=after_board.fen(), score=Score(cp=0), lines=[line(after_board, ["f6g8"], Score(cp=0))]
    )
    facts, m = review(board, before, after, "blunder")
    (fact,) = [f for f in facts if f.kind == "allows_repetition"]
    assert fact.actor == "black"
    assert fact.data == {"reply": "5...Ng8", "earlier": ["1...e5", "3...Ng8"]}
    assert not [f for f in facts if f.kind == "positional"]

    explanation = build_explanation(m, facts, "white")
    assert explanation.headline == "Allows a draw by repetition"
    assert explanation.sections[0].title == "What went wrong"
    assert explanation.sections[0].text == (
        "It lets your opponent repeat the position a third time with 5...Ng8 "
        "(it already came up after 1...e5 and 3...Ng8), so the game ends in a draw by repetition."
    )
    assert explanation.sections[1].title == "Better was 5.Nc3"
    assert explanation.lesson and "third time is a draw" in explanation.lesson
    assert explanation.hints[0].startswith("This position has come up before.")

    neutral = build_explanation(m, facts, None)
    assert neutral.sections[0].text.startswith("It lets Black repeat the position a third time")
