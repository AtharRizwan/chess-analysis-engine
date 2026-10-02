"""Tactic detectors vs lichess puzzle themes on a small committed sample (CC0).

Thresholds sit a little below what this sample measures today (the larger sample from
scripts/eval_motifs.py is the better accuracy estimate); the point is to catch regressions.
"""

import csv
from collections import defaultdict

import chess
import pytest

from chess_analysis_engine.facts.lines import Line
from chess_analysis_engine.facts.tactics import detect_motifs

# lichess theme(s) → (our name, minimum recall, minimum precision)
CHECKS = {
    ("fork",): ("fork", 0.72, 0.80),
    ("pin",): ("pin", 0.70, 0.90),
    ("skewer",): ("skewer", 0.88, 0.88),
    ("discoveredAttack", "discoveredCheck"): ("discovered", 0.80, 0.85),
    ("doubleCheck",): ("double_check", 0.88, 0.92),
    ("hangingPiece",): ("hanging_piece", 0.88, 0.92),
    ("backRankMate",): ("back_rank_mate", 0.92, 0.88),
    ("smotheredMate",): ("smothered_mate", 0.92, 0.92),
    ("trappedPiece",): ("trapped_piece", 0.85, 0.92),
}


def our_names(row: dict[str, str]) -> set[str]:
    board = chess.Board(row["FEN"])
    moves = row["Moves"].split()
    board.push_uci(moves[0])
    names = set()
    for motif in detect_motifs(Line.from_uci(board, moves[1:]), board.turn):
        if motif.name == "mate" and motif.detail.get("pattern"):
            names.add(motif.detail["pattern"])
        elif motif.name.startswith("discovered"):
            names.add("discovered")
        elif motif.name == "pin" and not motif.detail.get("absolute"):
            names.add("relative_pin")
        else:
            names.add(motif.name)
    return names


@pytest.fixture(scope="module")
def results(fixtures):
    with (fixtures / "puzzles_sample.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    tagged, found = defaultdict(set), defaultdict(set)
    for row in rows:
        for theme in row["Themes"].split():
            tagged[theme].add(row["PuzzleId"])
        for name in our_names(row):
            found[name].add(row["PuzzleId"])
    return tagged, found


@pytest.mark.parametrize(("themes", "expected"), list(CHECKS.items()), ids=[t[0] for t in CHECKS])
def test_detector_matches_lichess_themes(results, themes, expected):
    tagged, found = results
    name, min_recall, min_precision = expected
    positives = set().union(*(tagged[t] for t in themes))
    ours = found[name]
    recall = len(positives & ours) / len(positives)
    precision = len(positives & ours) / len(ours) if ours else 0.0
    assert recall >= min_recall, f"{name} recall {recall:.2f}"
    assert precision >= min_precision, f"{name} precision {precision:.2f}"
