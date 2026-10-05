from dataclasses import replace

import pytest

from chess_analysis_engine.engine.scoring import missed_mate
from chess_analysis_engine.models import Score
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


def test_punishing_the_opponents_mistake_is_great():
    best = replace(BASE, played_uci="d2d4", second_best_ep=0.59)  # not an only-move
    assert classify(best) == "best"
    # Right after an opponent's error that cost them 0.15, the best move is the punishment...
    assert classify(replace(best, opponent_prev_loss=0.15)) == "great"
    # ...even when it simply takes material or the game was already won (like chess.com).
    assert classify(replace(best, opponent_prev_loss=0.15, takes_material=True, ep_before=0.95)) == "great"
    # A small slip by the opponent doesn't make the reply great.
    assert classify(replace(best, opponent_prev_loss=0.04)) == "best"


def test_losing_a_forced_mate_is_a_miss():
    winning = replace(BASE, ep_before=1.0, second_best_ep=0.95)
    # Mate in 1 was there; the move still wins easily but the mate is gone (or longer).
    assert classify(replace(winning, ep_after=0.97, missed_mate=True)) == "miss"
    assert classify(replace(winning, ep_after=1.0, missed_mate=True)) == "miss"
    # Throwing away the whole win is still a blunder.
    assert classify(replace(winning, ep_after=0.40, missed_mate=True)) == "blunder"
    # The engine's own move is never a miss.
    assert classify(replace(winning, played_uci="d2d4", ep_after=1.0, missed_mate=True)) == "best"


def test_missed_mate_detection():
    # Like chess.com: a mate in 1 left on the board is a miss, even if a slower mate remains...
    assert missed_mate("white", Score(mate=1), Score(mate=2))
    # ...but a mate in 2 or 3 that just takes a little longer isn't.
    assert not missed_mate("white", Score(mate=3), Score(mate=5))
    assert not missed_mate("white", Score(mate=3), Score(mate=2))  # on the shortest path
    # A short mate gone altogether is a miss, however winning you still are.
    assert missed_mate("white", Score(mate=3), Score(cp=1100))
    assert missed_mate("black", Score(mate=-2), Score(cp=-900))  # Black's mate, from White's side
    # A long mate given up for a still-crushing position isn't; for anything less, it is.
    assert not missed_mate("white", Score(mate=6), Score(cp=1200))
    assert missed_mate("white", Score(mate=6), Score(cp=700))
    assert not missed_mate("white", Score(mate=1), Score(result="1-0"))  # delivered it
    assert not missed_mate("white", Score(mate=-2), Score(mate=-1))  # being mated isn't "missing" one


def test_obvious_only_moves_are_not_great():
    only = replace(BASE, played_uci="d2d4", second_best_ep=0.45)
    assert classify(replace(only, takes_material=True)) == "best"  # taking what was left hanging
    assert classify(replace(only, rescues_piece=True)) == "best"  # moving the attacked piece away
    assert classify(replace(only, in_check=True, legal_moves=12)) == "best"  # getting out of check
    # An only-move that just keeps a won game won.
    assert classify(replace(only, ep_before=0.95, ep_after=0.95, second_best_ep=0.80)) == "best"


def test_brilliant_needs_a_sound_sacrifice_that_matters():
    # The sacrifice keeps the balance; the quiet alternatives would have left you clearly worse.
    sac = replace(BASE, played_uci="d2d4", sacrifice=300, ep_after=0.62, second_best_ep=0.45)
    assert classify(sac) == "brilliant"
    # Pawn offers don't count.
    assert classify(replace(sac, sacrifice=100)) == "great"  # still an only-move, but no sacrifice
    # If quiet moves also win easily, the sacrifice isn't special.
    assert classify(replace(sac, ep_before=0.99, ep_after=0.99, second_best_ep=0.97)) == "best"
    # Nor if a quiet move does about as well (the sacrifice wasn't needed).
    assert classify(replace(sac, ep_before=0.88, ep_after=0.88, second_best_ep=0.87)) == "best"
    # Nor if it isn't the engine's move.
    assert classify(replace(sac, played_uci="c2c4", ep_after=0.59)) == "excellent"
    # A sacrifice that forces mate while quiet moves only keep an edge is (Morphy's 16.Qb8+).
    assert classify(replace(sac, ep_before=1.0, ep_after=1.0, second_best_ep=0.86)) == "brilliant"
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
