"""Measure our tactic detectors against the theme tags of the lichess puzzle database (CC0).

    uv run python scripts/eval_motifs.py --per-theme 200

The first run streams https://database.lichess.org/lichess_db_puzzle.csv.zst and keeps a sample
of puzzles per theme in data/puzzles/ (no need to download the whole file again). For every
theme we report recall (tagged puzzles where we find the motif) and precision (puzzles where we
find the motif that lichess also tagged with it), measured over the pooled sample.

Puzzle format: FEN is the position *before* the opponent's last move; the first UCI move in
`Moves` is that move, the rest is the solution for the side to move afterwards.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from collections import Counter, defaultdict
from pathlib import Path

import chess
import httpx

from chess_analysis_engine.facts.lines import Line
from chess_analysis_engine.facts.tactics import detect_motifs

PUZZLE_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "data" / "puzzles"

# lichess theme → our motif name (mate patterns are matched on the "mate" motif's pattern).
THEMES = {
    "fork": "fork",
    "pin": "pin",
    "skewer": "skewer",
    "discovered": "discovered",  # discoveredAttack or discoveredCheck
    "doubleCheck": "double_check",
    "hangingPiece": "hanging_piece",
    "trappedPiece": "trapped_piece",
    "capturingDefender": "removal_of_defender",
    "deflection": "deflection",
    "attraction": "attraction",
    "intermezzo": "zwischenzug",
    "sacrifice": "sacrifice",
    "promotion": "promotion",
    "quietMove": "quiet_move",
    "backRankMate": "back_rank_mate",
    "smotheredMate": "smothered_mate",
    "anastasiaMate": "anastasia_mate",
    "arabianMate": "arabian_mate",
    "bodenMate": "boden_mate",
    "doubleBishopMate": "double_bishop_mate",
    "dovetailMate": "dovetail_mate",
}
FIELDS = ["PuzzleId", "FEN", "Moves", "Rating", "Themes"]


def stream_sample(per_theme: int, max_rows: int) -> list[dict[str, str]]:
    import zstandard

    wanted = Counter({theme: per_theme for theme in THEMES})
    chosen: list[dict[str, str]] = []
    with httpx.stream("GET", PUZZLE_URL, timeout=120, follow_redirects=True) as response:
        response.raise_for_status()
        reader = zstandard.ZstdDecompressor().stream_reader(_IterStream(response.iter_bytes()))
        rows = csv.DictReader(io.TextIOWrapper(reader, encoding="utf-8"))
        for n, row in enumerate(rows):
            themes = set(row["Themes"].split())
            hits = [t for t in themes if wanted[t] > 0]
            if hits or n < per_theme * 4:  # plus untargeted puzzles as a background for precision
                for t in hits:
                    wanted[t] -= 1
                chosen.append({k: row[k] for k in FIELDS})
            if n % 100_000 == 0:
                left = sum(v for v in wanted.values() if v > 0)
                print(f"\rscanned {n:,} puzzles, {left} samples still wanted", end="", file=sys.stderr)
            if not +wanted or n >= max_rows:
                break
    print(file=sys.stderr)
    return chosen


class _IterStream(io.RawIOBase):
    def __init__(self, chunks):
        self._chunks = iter(chunks)
        self._buffer = b""

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        while not self._buffer:
            try:
                self._buffer = next(self._chunks)
            except StopIteration:
                return 0
        n = min(len(b), len(self._buffer))
        b[:n] = self._buffer[:n]
        self._buffer = self._buffer[n:]
        return n


def load_sample(per_theme: int, max_rows: int) -> list[dict[str, str]]:
    path = SAMPLE_DIR / f"sample-{per_theme}.csv"
    if path.exists():
        with path.open(newline="") as fh:
            return list(csv.DictReader(fh))
    rows = stream_sample(per_theme, max_rows)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def our_motifs(row: dict[str, str]) -> set[str]:
    board = chess.Board(row["FEN"])
    moves = row["Moves"].split()
    board.push_uci(moves[0])
    line = Line.from_uci(board, moves[1:])
    names: set[str] = set()
    for motif in detect_motifs(line, board.turn):
        if motif.name == "mate" and motif.detail.get("pattern"):
            names.add(motif.detail["pattern"])
        elif motif.name in ("discovered_attack", "discovered_check"):
            names.add("discovered")
        elif motif.name == "pin" and not motif.detail.get("absolute"):
            names.add("relative_pin")  # lichess only tags pins to the king
        else:
            names.add(motif.name)
    return names


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-theme", type=int, default=200)
    parser.add_argument("--max-rows", type=int, default=3_000_000)
    parser.add_argument("--show-misses", metavar="THEME", help="print puzzles we miss for a theme")
    parser.add_argument("--show-extra", metavar="THEME", help="print puzzles we tag but lichess doesn't")
    args = parser.parse_args()

    rows = load_sample(args.per_theme, args.max_rows)
    tagged: dict[str, set[str]] = defaultdict(set)  # theme → puzzle ids tagged with it
    found: dict[str, set[str]] = defaultdict(set)  # our name → puzzle ids where we found it
    for row in rows:
        ours = our_motifs(row)
        for theme in row["Themes"].split():
            tagged[theme].add(row["PuzzleId"])
        for name in ours:
            found[name].add(row["PuzzleId"])

    # lichess tags a discovered check as "discoveredCheck" *instead of* "discoveredAttack".
    tagged["discovered"] = tagged["discoveredAttack"] | tagged["discoveredCheck"]

    print(f"{len(rows)} puzzles\n")
    print(f"{'lichess theme':<20}{'tagged':>8}{'recall':>9}{'precision':>11}")
    for theme, name in THEMES.items():
        positives = tagged.get(theme, set())
        ours = found.get(name, set())
        recall = len(positives & ours) / len(positives) if positives else float("nan")
        precision = len(positives & ours) / len(ours) if ours else float("nan")
        print(f"{theme:<20}{len(positives):>8}{recall:>9.2f}{precision:>11.2f}")
    by_id = {r["PuzzleId"]: r for r in rows}
    listings = []
    if args.show_misses:
        listings.append(tagged[args.show_misses] - found[THEMES[args.show_misses]])
    if args.show_extra:
        listings.append(found[THEMES[args.show_extra]] - tagged[args.show_extra])
    for ids in listings:
        for pid in sorted(ids)[:20]:
            r = by_id[pid]
            print(f"{pid}  {r['FEN']}  {r['Moves']}  lichess={r['Themes']}  ours={sorted(our_motifs(r))}")


if __name__ == "__main__":
    main()
