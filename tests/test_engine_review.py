"""Integration tests against a real Stockfish (run with `pytest -m engine`)."""

import chess
import pytest

from chess_analysis_engine.config import PRESETS
from chess_analysis_engine.explain.coach_llm import Grounding
from chess_analysis_engine.pgn import read_games
from chess_analysis_engine.review.pipeline import ReviewOptions, review_game

pytestmark = pytest.mark.engine


def test_multipv_lines_and_mate_scores(pool):
    result = pool.analyse(chess.Board(), depth=10, multipv=3)
    assert len(result.lines) == 3
    assert all(line.san and line.uci for line in result.lines)

    back_rank = chess.Board("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1")
    result = pool.analyse(back_rank, depth=10, multipv=1)
    assert result.score.mate == 1
    assert result.best is not None and result.best.san[0] == "Rd8#"


def test_finished_games_need_no_engine(pool):
    mated = chess.Board("3R2k1/5ppp/8/8/8/8/5PPP/6K1 b - - 1 1")
    assert pool.analyse(mated, depth=10).score.result == "1-0"


def test_opera_game_review(pool, fixtures):
    (game,) = read_games((fixtures / "opera_game.pgn").read_text())
    review = review_game(game, pool, ReviewOptions(preset=PRESETS["quick"], user_color="white"))
    by_san = {(m.color, m.san): m for m in review.moves}

    assert by_san[("white", "Qb8+")].classification == "brilliant"
    assert by_san[("white", "Rd8#")].classification == "best"
    assert by_san[("black", "Nxb8")].classification == "forced"
    black_errors = [
        m for m in review.moves if m.color == "black" and m.classification in ("mistake", "blunder")
    ]
    assert black_errors, "Black's opening play should contain at least one mistake"
    assert review.summary["white"].accuracy > review.summary["black"].accuracy
    assert review.opening is not None and review.opening.eco == "C41"
    assert review.final_eval is not None and review.final_eval.result == "1-0"


def _review(pool, fixtures, game_index: int, user):
    games = read_games((fixtures / "beginner_traps.pgn").read_text())
    return review_game(games[game_index], pool, ReviewOptions(preset=PRESETS["quick"], user_color=user))


def _move(review, color, san):
    return next(m for m in review.moves if m.color == color and m.san == san)


def test_blackburne_shilling_trap_explanations(pool, fixtures):
    review = _review(pool, fixtures, 0, "white")

    greedy = _move(review, "white", "Nxe5")
    attack = next(f for f in greedy.facts if f.kind == "allows_attack")
    assert attack.data["key_move"] == "4...Qg5"
    assert {t["square"] for t in attack.data["targets"]} == {"g2", "e5"}
    text = " ".join(s.text for s in greedy.explanation.sections)
    assert "4...Qg5" in text and "at the same time" in text

    blunder = _move(review, "white", "Nxf7")
    assert blunder.classification == "blunder"
    kinds = [f.kind for f in blunder.facts]
    assert "ignored_threat" in kinds
    assert blunder.explanation.lesson and "threaten" in blunder.explanation.lesson
    assert any("defends your pawn on g2" in s.text for s in blunder.explanation.sections)


def test_legals_mate_explanations(pool, fixtures):
    review = _review(pool, fixtures, 1, "black")

    queen_grab = _move(review, "black", "Bxd1")
    mate = next(f for f in queen_grab.facts if f.kind == "allows_mate")
    assert mate.data["mate_in"] == 2
    assert queen_grab.explanation.headline == "Allows mate in 2"

    slip = _move(review, "black", "g6")
    threat = next(f for f in slip.facts if f.kind == "ignored_threat")
    assert threat.motif == "discovered_attack"
    assert "unmasks their queen on d1 against your bishop on g4" in slip.explanation.sections[0].text


def test_coach_checks_accept_every_template_explanation(pool, fixtures):
    """The template text is verified, so the coach's grounding checks must never reject it."""
    for index, user in ((0, "white"), (1, "black")):
        review = _review(pool, fixtures, index, user)
        for m in review.moves:
            grounding = Grounding.of(m, user)
            texts = [m.explanation.headline, m.explanation.lesson or ""] + [
                s.text for s in m.explanation.sections
            ]
            for text in texts:
                grounding.check_text("text", text)
            assert grounding.problems == [], (m.san, grounding.problems)
