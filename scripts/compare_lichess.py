"""Cross-check our move classification against lichess's own server analysis.

    uv run python scripts/compare_lichess.py <lichess-username> [--games 3] [--preset quick]

Fetches recent games that were analysed on lichess, reviews them with our pipeline and
reports how often the two agree on mistakes and blunders.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

import httpx

from chess_analysis_engine.config import PRESETS
from chess_analysis_engine.importers.common import USER_AGENT
from chess_analysis_engine.pgn import read_games
from chess_analysis_engine.review.pipeline import ReviewOptions, review_game
from chess_analysis_engine.services import open_pool

OURS = {"inaccuracy": "Inaccuracy", "mistake": "Mistake", "miss": "Mistake", "blunder": "Blunder"}


def fetch_analysed(username: str, count: int) -> list[dict]:
    params = {
        "max": str(count),
        "analysed": "true",
        "evals": "true",
        "pgnInJson": "true",
        "perfType": "blitz,rapid,classical",
    }
    headers = {"Accept": "application/x-ndjson", "User-Agent": USER_AGENT}
    with httpx.Client(timeout=120) as http:
        r = http.get(f"https://lichess.org/api/games/user/{username}", params=params, headers=headers)
        r.raise_for_status()
        return [json.loads(line) for line in r.text.splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--games", type=int, default=3)
    parser.add_argument("--preset", default="quick", choices=sorted(PRESETS))
    args = parser.parse_args()

    games = [g for g in fetch_analysed(args.username, args.games) if g.get("analysis")]
    print(f"{len(games)} analysed games")
    confusion: Counter[tuple[str, str]] = Counter()
    with open_pool() as pool:
        for raw in games:
            (game,) = read_games(raw["pgn"])
            review = review_game(game, pool, ReviewOptions(preset=PRESETS[args.preset]))
            for move, judged in zip(review.moves, raw["analysis"], strict=False):
                theirs = judged.get("judgment", {}).get("name", "-")
                ours = OURS.get(move.classification, "-")
                confusion[(theirs, ours)] += 1
                if {theirs, ours} & {"Mistake", "Blunder"} and theirs != ours:
                    where = f"{raw['id']} ply {move.ply:3d} {move.san:8s}"
                    print(f"  {where} lichess={theirs:10s} ours={move.classification}")

    labels = ["-", "Inaccuracy", "Mistake", "Blunder"]
    print("\nrows: lichess, columns: ours")
    print(" " * 12 + "".join(f"{label:>12s}" for label in labels))
    for theirs in labels:
        print(f"{theirs:>12s}" + "".join(f"{confusion[(theirs, ours)]:12d}" for ours in labels))
    serious_theirs = sum(v for (t, _), v in confusion.items() if t in ("Mistake", "Blunder"))
    caught = sum(v for (t, o), v in confusion.items() if t in ("Mistake", "Blunder") and o != "-")
    if serious_theirs:
        print(f"\nlichess mistakes/blunders we also flag (any level): {caught}/{serious_theirs}")


if __name__ == "__main__":
    main()
