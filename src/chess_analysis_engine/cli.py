"""Command line: `chess-analysis doctor | analyze | import | serve`."""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

import chess

from chess_analysis_engine import __version__
from chess_analysis_engine.config import PRESETS, data_dir, find_stockfish
from chess_analysis_engine.pgn import PgnError, detect_user_color, read_games
from chess_analysis_engine.report import render_markdown
from chess_analysis_engine.review.pipeline import ReviewOptions, review_game
from chess_analysis_engine.services import EngineNotFound, default_db, open_pool


def _progress(stage: str, done: int, total: int) -> None:
    labels = {
        "engine": "Analyzing positions",
        "critical": "Re-checking critical moves",
        "facts": "Explaining moves",
    }
    end = "\n" if done == total else ""
    print(f"\r{labels.get(stage, stage)}: {done}/{total}", end=end, file=sys.stderr, flush=True)


def cmd_doctor(_: argparse.Namespace) -> int:
    ok = True
    print(f"chess-analysis-engine {__version__}, python-chess {chess.__version__}")
    path = find_stockfish()
    if path:
        try:
            with open_pool(size=1, hash_mb=16) as pool:
                print(f"Engine: {pool.name} ({path})")
        except Exception as exc:  # report any engine start-up failure
            ok = False
            print(f"Engine: failed to start {path}: {exc}")
    else:
        ok = False
        print("Engine: not found — run ./scripts/get_stockfish.sh or `yay -S stockfish`")
    print(f"Data directory: {data_dir()}")
    from chess_analysis_engine.review.openings import load_book

    print(f"Opening book: {len(load_book().named)} named lines")
    coach = importlib.util.find_spec("anthropic") is not None
    key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    print(
        f"Claude coach (optional): sdk {'installed' if coach else 'not installed'}, "
        f"credentials {'found' if key else 'not set'}"
    )
    from chess_analysis_engine.explain.coach_cli import make_cli_client
    from chess_analysis_engine.explain.coach_llm import CoachError

    try:
        make_cli_client()
        claude_code = "ready"
    except CoachError as exc:
        claude_code = str(exc)
    print(f"Claude coach on your Claude plan, through Claude Code (optional): {claude_code}")
    return 0 if ok else 1


def cmd_analyze(args: argparse.Namespace) -> int:
    text = sys.stdin.read() if args.pgn == "-" else Path(args.pgn).read_text(encoding="utf-8")
    try:
        games = read_games(text)
    except PgnError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not 1 <= args.game <= len(games):
        print(
            f"The PGN has {len(games)} game(s); --game must be between 1 and {len(games)}.", file=sys.stderr
        )
        return 2
    game = games[args.game - 1]
    user_color = args.side if args.side in ("white", "black") else detect_user_color(game, args.user)
    db = default_db()
    try:
        with open_pool(db, args.engines, args.hash) as pool:
            options = ReviewOptions(preset=PRESETS[args.preset], user_color=user_color)
            review = review_game(game, pool, options, progress=_progress, db=db)
    except EngineNotFound as exc:
        print(exc, file=sys.stderr)
        return 1
    output = render_markdown(review) if args.format == "md" else review.model_dump_json(indent=2)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(output)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from chess_analysis_engine.importers import chesscom, lichess
    from chess_analysis_engine.importers.common import ImportFailed, save_games

    try:
        fetch = chesscom.fetch_recent if args.source == "chesscom" else lichess.fetch_recent
        games = fetch(args.username, max_games=args.max)
    except ImportFailed as exc:
        print(exc, file=sys.stderr)
        return 1
    saved = save_games(default_db(), games)
    new = sum(1 for _, created in saved if created)
    for game, (game_id, _) in zip(games, saved, strict=True):
        side = game.user_color or "?"
        print(
            f"#{game_id:<5} {game.played_at or '':<26} {game.white} vs {game.black}  {game.result}  "
            f"(you: {side})"
        )
    print(f"{len(games)} games fetched, {new} new.", file=sys.stderr)
    if args.out:
        Path(args.out).write_text("\n\n".join(g.pgn.strip() for g in games) + "\n", encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("chess_analysis_engine.api.app:create_app", factory=True, host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chess-analysis", description="Chess game review that explains why."
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check that Stockfish and the data files are available")
    doctor.set_defaults(func=cmd_doctor)

    analyze = sub.add_parser("analyze", help="review a game from a PGN file")
    analyze.add_argument("pgn", help="PGN file, or - for stdin")
    analyze.add_argument("--game", type=int, default=1, help="which game in the file (1-based)")
    analyze.add_argument("--side", choices=["white", "black", "auto"], default="auto", help="your side")
    analyze.add_argument("--user", action="append", default=[], help="your username (for --side auto)")
    analyze.add_argument("--preset", choices=sorted(PRESETS), default="standard")
    analyze.add_argument("--format", choices=["md", "json"], default="md")
    analyze.add_argument("--out", help="write the report here instead of stdout")
    analyze.add_argument("--engines", type=int, help="parallel single-threaded engines (default: cores-2)")
    analyze.add_argument("--hash", type=int, help="hash size per engine in MB (default 64)")
    analyze.set_defaults(func=cmd_analyze)

    imp = sub.add_parser("import", help="fetch your recent games from chess.com or lichess")
    imp.add_argument("source", choices=["chesscom", "lichess"])
    imp.add_argument("username")
    imp.add_argument("--max", type=int, default=20, help="how many games")
    imp.add_argument("--out", help="also write the games to this PGN file")
    imp.set_defaults(func=cmd_import)

    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
