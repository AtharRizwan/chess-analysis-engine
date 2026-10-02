from dataclasses import replace

import pytest

from chess_analysis_engine.review.classify import MoveContext, classify

BASE = MoveContext(
    played_uci="e2e4",
    best_uci="d2d4",
    ep_before=0.60,
    ep_after=0.60,
    second_best_ep=0.58,
    legal_moves=30,
)


@pytest.mark.parametrize(
    ("ep_after", "expected"),
    [
        (0.59, "excellent"),
        (0.57, "good"),
        (0.53, "inaccuracy"),
        (0.45, "mistake"),
        (0.35, "blunder"),
    ],
)
def test_loss_thresholds(ep_after, expected):
    assert classify(replace(BASE, ep_after=ep_after)) == expected


def test_playing_the_engine_move_is_best_even_with_search_noise():
    assert classify(replace(BASE, played_uci="d2d4", ep_after=0.57)) == "best"


def test_forced_and_book_take_precedence():
    assert classify(replace(BASE, legal_moves=1, ep_after=0.1)) == "forced"
    assert classify(replace(BASE, book=True)) == "book"


def test_great_is_an_only_move():
    only = replace(BASE, played_uci="d2d4", second_best_ep=0.45)
    assert classify(only) == "great"
    assert classify(replace(only, is_recapture=True)) == "best"
    assert classify(replace(only, delivers_mate=True)) == "best"
    assert classify(replace(only, in_check=True, legal_moves=2)) == "best"


def test_brilliant_needs_a_sound_sacrifice_that_matters():
    sac = replace(BASE, played_uci="d2d4", sacrifice=300, ep_after=0.62)
    assert classify(sac) == "brilliant"
    # Pawn offers don't count.
    assert classify(replace(sac, sacrifice=100)) == "best"
    # If quiet moves also win easily, the sacrifice isn't special.
    assert classify(replace(sac, ep_before=0.99, ep_after=0.99, second_best_ep=0.97)) == "best"
    # A sacrifice that leaves you worse isn't brilliant.
    assert classify(replace(sac, ep_before=0.40, ep_after=0.40, second_best_ep=0.38)) == "best"


def test_miss_is_failing_to_punish_without_falling_below_the_start():
    # Opponent's last move cost them 0.30; we stood at 0.50 before it, at 0.80 after it.
    gift = replace(
        BASE, ep_before=0.80, second_best_ep=0.70, opponent_prev_loss=0.30, ep_before_opponent_error=0.50
    )
    assert classify(replace(gift, ep_after=0.55)) == "miss"
    # Giving back more than the gift is a plain blunder.
    assert classify(replace(gift, ep_after=0.40)) == "blunder"
    # Small slips after a gift are still judged normally.
    assert classify(replace(gift, ep_after=0.74)) == "inaccuracy"
