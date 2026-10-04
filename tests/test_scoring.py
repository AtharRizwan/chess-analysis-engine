import pytest

from chess_analysis_engine.engine.scoring import (
    LABEL_K,
    K,
    cp_to_ep,
    ep_for,
    game_accuracy,
    move_accuracy,
    white_ep,
    white_win_percent,
)
from chess_analysis_engine.models import Score


def test_cp_to_ep_is_a_symmetric_curve():
    assert cp_to_ep(0) == 0.5
    assert cp_to_ep(100) == pytest.approx(0.591, abs=1e-3)
    assert cp_to_ep(300) == pytest.approx(0.751, abs=1e-3)
    assert cp_to_ep(-300) == pytest.approx(1 - cp_to_ep(300))


def test_mates_and_results_are_certain():
    assert white_ep(Score(mate=3)) == 1.0
    assert white_ep(Score(mate=-1)) == 0.0
    assert white_ep(Score(result="0-1")) == 0.0
    assert white_ep(Score(result="1/2-1/2")) == 0.5
    assert ep_for(Score(mate=2), "black") == 0.0


def test_win_percent_is_capped_like_lichess():
    assert white_win_percent(Score(cp=5000)) == pytest.approx(white_win_percent(Score(cp=1000)))
    assert white_win_percent(Score(mate=4)) == pytest.approx(97.55, abs=0.01)
    assert white_win_percent(Score(result="1-0")) == 100.0


def test_move_accuracy():
    assert move_accuracy(60, 60) == 100.0
    assert move_accuracy(60, 70) == 100.0
    assert move_accuracy(60, 50) == pytest.approx(64.6, abs=0.1)
    assert move_accuracy(90, 0) == 0.0


def test_game_accuracy_rewards_the_side_that_kept_its_chances():
    steady = [50.0] * 21
    assert game_accuracy(steady) == {"white": 100.0, "black": 100.0}

    # Black blunders on their 5th move (ply 10): White's win% jumps from 50 to 90.
    swing = [50.0] * 10 + [90.0] * 11
    acc = game_accuracy(swing)
    assert acc["white"] == 100.0
    assert acc["black"] < 90.0


def test_game_accuracy_handles_tiny_games():
    assert game_accuracy([50.0]) == {"white": None, "black": None}
    acc = game_accuracy([50.0, 50.0])
    assert acc["white"] == 100.0
    assert acc["black"] is None


def test_labels_use_a_flatter_curve_than_winning_chances():
    assert LABEL_K < K
    swing = lambda k: ep_for(Score(cp=200), "white", k) - ep_for(Score(cp=0), "white", k)  # noqa: E731
    decided = lambda k: ep_for(Score(cp=1200), "white", k) - ep_for(Score(cp=800), "white", k)  # noqa: E731
    # Throwing away a two-pawn edge in a level game costs less on the label curve...
    assert swing(LABEL_K) < swing(K)
    # ...and +12 → +8 in a decided game costs more.
    assert decided(LABEL_K) > decided(K)
    assert ep_for(Score(mate=4), "white") == 1.0 and ep_for(Score(mate=4), "black") == 0.0
    # Winning chances (the graph, accuracy) stay on lichess's curve.
    assert white_win_percent(Score(cp=300)) == pytest.approx(100 * cp_to_ep(300))
