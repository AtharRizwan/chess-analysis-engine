# chess-analysis-engine

A local chess game review that explains **why**: why your move was bad (or good, or good but not best),
what the better move actually achieves, and the general lesson to keep. It then turns your own
mistakes into puzzles and shows which kinds of mistakes cost you the most.

Every explanation is built from **verified facts**. A fork is only called a fork if the engine's line
really wins the forked material, and a threat is only mentioned if a search shows it was there. When
there's no clean reason, the review says so and shows the lines. An optional Claude "coach voice" can
retell a move in more natural words, but its text is checked against the same facts before you see it.

## Setup

Requires Python ≥ 3.12 with [uv](https://docs.astral.sh/uv/), Node ≥ 20.19 (for the web app) and Stockfish.

```sh
uv sync                          # Python dependencies
scripts/get_stockfish.sh         # official Stockfish 19 binary into ./bin (or install `stockfish` on PATH)
uv run chess-analysis doctor     # checks Stockfish and the data files
npm --prefix web install && npm --prefix web run build
```

Stockfish is looked up in `CAE_STOCKFISH_PATH`, then `./bin/stockfish`, then `PATH`. Data (games,
reviews, engine cache, drills) lives in `~/.local/share/chess-analysis-engine/` (override with
`CAE_DATA_DIR`).

## Use it

```sh
uv run chess-analysis serve      # web app on http://127.0.0.1:8000
```

1. **Settings:** enter your chess.com and/or lichess username so your side is recognised.
2. **Games:** import your recent games (or paste a PGN), then review them. Progress is shown live.
3. **Review:** step through the game. Each move shows what went wrong, what was better (with a line you
   can play through on the board) and the lesson. Drag any piece to ask "why not this move?".
4. **Learn mode** (on by default): on your mistakes the answer is hidden until you've tried, with
   hints that get more specific.
5. **Drills:** every mistake, miss and blunder of yours becomes a puzzle, repeated after 1, 3, 7, 14
   and 30 days.
6. **Insights:** what keeps costing you points across games (hanging pieces, ignored threats, missed
   forks…), accuracy by game phase and over time, with links to examples and themed drills.

From the command line:

```sh
uv run chess-analysis import chesscom <username> --max 20 --out mygames.pgn
uv run chess-analysis analyze mygames.pgn --game 1 --side auto --user <username> --preset standard
uv run chess-analysis analyze game.pgn --side white --format json --out review.json
```

Presets: `quick` (depth 14), `standard` (depth 18, the default) and `deep` (depth 22). Critical
moves are always re-searched 4 plies deeper.

## How the review works

1. **Engine pass:** every position with MultiPV 3, spread over several single-threaded Stockfish
   processes, cached in SQLite.
2. **Classification:** expected points lost per move, with chess.com-style thresholds. The curve and
   thresholds behind the labels were fitted to chess.com's Game Review of 44 real games, checked on
   games held out of the fit:
   - the win-chance curve is flatter than lichess's, so a two-pawn swing in a level position weighs
     less, and squandering a decided position weighs more;
   - the Good/Inaccuracy boundary sits at 0.04 expected points instead of chess.com's published 0.05.

   It is one fixed setup, not adjusted to anyone's rating. The winning-chances graph and accuracy keep
   lichess's curve and formula. Labels go from Best to Blunder, plus:
   - **Book** and **Forced**;
   - **Great:** either the best move right after your opponent's clear mistake (finding the
     punishment), or a hard-to-find only move. For the only-move case, obvious ones don't count: taking
     material, recapturing, saving an attacked piece, getting out of check, or keeping an already-won
     game won.
   - **Brilliant:** the engine's move, putting at least an exchange newly on offer, and clearly better
     than every quieter move;
   - **Miss:** failing to punish an error, or missing a forced mate. That means leaving a mate in 1 on
     the board, or giving up a mate altogether when it was short (mate in 3 or less) or when what's left
     isn't crushing.

   chess.com's own labels change between two reviews of the same game: about 7 in 10 stay the same.
   On those 44 games ours match chess.com's about 6 times in 10.
3. **Facts:** static exchange evaluation (SEE), hanging pieces, tactic detectors (fork, pin, skewer,
   discovered attack, double check and more) confirmed on the engine line, named mate patterns,
   null-move threat searches ("what was your opponent threatening?"), positional comparisons, clock
   use and the tablebase for endgames with 7 pieces or fewer.
4. **Explanations:** templates turn the ranked facts into "what went wrong", "better was" and "lesson"
   sections, with arrows on the board.

The tactic detectors are benchmarked against the lichess puzzle database (`scripts/eval_motifs.py`).
Fork, pin, skewer, discovered attack, double check, hanging piece, back-rank mate and smothered mate
all reach 0.8 or better on both precision and recall. Motifs that can't be detected that reliably are
never named.

## Optional: Claude coach

```sh
uv sync --extra coach
ANTHROPIC_API_KEY=... uv run chess-analysis serve
```

Then turn the coach on in Settings, and use **✦ Coach voice** on any move. Key moments and mistakes are
narrated automatically; other moves have an "Ask the coach" button. The default model is
`claude-opus-5-5` at medium effort, and both can be changed in Settings.

- Claude receives only the verified facts, the engine lines, the board and the template draft.
- Every reply is checked automatically:
  - each move named must be in the lines or legal for that side;
  - each "piece on square" must be true;
  - there must be no invented evaluation numbers;
  - every cited fact must exist;
  - a mistake's better move must be the engine's move.
- A reply that fails gets one correction round. If it fails again, the standard explanation is shown
  with a note saying why. Coach text is marked "✦ AI", and the facts and lines always stay visible.
- Narrations are cached, so each move is paid for once. Token usage and an estimated cost are shown in
  Settings.
- The system prompt is cached (prompt caching). Requests use server-side refusal fallback
  (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`), which a chess review shouldn't need.

Without the extra package or an API key, everything else works exactly the same.

## Development

```sh
uv run pytest                    # unit tests (no engine, no network)
uv run pytest -m engine          # Stockfish integration tests
uv run ruff check src tests && uv run ruff format --check src tests
npm --prefix web run dev         # Vite dev server (proxies /api to :8000)
npm --prefix web run test        # vitest
npm --prefix web run gen:api     # regenerate TypeScript types from the API schema
uv run python scripts/eval_motifs.py --per-theme 200   # tactic detector benchmark (downloads the puzzle DB)
```

## Credits and license

- [Stockfish](https://stockfishchess.org/) (GPL-3.0), [python-chess](https://github.com/niklasf/python-chess)
  (GPL-3.0), and [chessground](https://github.com/lichess-org/chessground) and
  [chessops](https://github.com/niklasf/chessops) (GPL-3.0).
- Opening names: lichess [chess-openings](https://github.com/lichess-org/chess-openings) (CC0). Puzzle
  benchmark: the [lichess puzzle database](https://database.lichess.org/#puzzles) (CC0).
- Win-chance and accuracy formulas follow lichess. The endgame tablebase is lichess's tablebase API.

Licensed under GPL-3.0-or-later (see `LICENSE`).
