"""PGN parsing: mainline moves, clock times and which side the user played."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field

import chess
import chess.pgn

from chess_analysis_engine.models import Color

STANDARD_VARIANTS = {"", "standard", "chess", "from position"}


class PgnError(ValueError):
    pass


@dataclass
class GameRecord:
    headers: dict[str, str]
    start_fen: str
    moves: list[chess.Move]
    sans: list[str]
    clocks: list[float | None] = field(default_factory=list)  # time left after each ply

    @property
    def white(self) -> str:
        return self.headers.get("White", "White")

    @property
    def black(self) -> str:
        return self.headers.get("Black", "Black")

    @property
    def result(self) -> str:
        return self.headers.get("Result", "*")

    def rating(self, color: Color) -> int | None:
        value = self.headers.get("WhiteElo" if color == "white" else "BlackElo", "")
        return int(value) if value.isdigit() else None

    @property
    def time_control(self) -> tuple[float, float] | None:
        """(base seconds, increment seconds), or None for daily / unknown games."""
        tc = self.headers.get("TimeControl", "")
        if not tc or tc == "-" or "/" in tc:
            return None
        base, _, inc = tc.partition("+")
        try:
            return float(base), float(inc or 0)
        except ValueError:
            return None

    def boards(self) -> list[chess.Board]:
        """Board before every ply plus the final position, each with full move history."""
        board = chess.Board(self.start_fen)
        result = [board.copy()]
        for move in self.moves:
            board.push(move)
            result.append(board.copy())
        return result

    def time_spent(self) -> list[float | None]:
        """Seconds each move took, from %clk comments (None when clocks are missing)."""
        tc = self.time_control
        spent: list[float | None] = []
        for i, remaining in enumerate(self.clocks):
            previous = self.clocks[i - 2] if i >= 2 else (tc[0] if tc else None)
            if remaining is None or previous is None:
                spent.append(None)
                continue
            increment = tc[1] if tc else 0.0
            spent.append(max(0.0, previous - remaining + increment))
        return spent

    def fingerprint(self) -> str:
        """Stable id for games pasted as PGN (used to de-duplicate imports)."""
        text = "|".join([self.start_fen, *[m.uci() for m in self.moves], self.white, self.black])
        return hashlib.sha1(text.encode()).hexdigest()[:16]


def read_games(pgn_text: str) -> list[GameRecord]:
    """Parse every game in a PGN string (mainline only)."""
    stream = io.StringIO(pgn_text)
    games: list[GameRecord] = []
    while (game := chess.pgn.read_game(stream)) is not None:
        if game.errors:
            raise PgnError(f"Could not read game {len(games) + 1}: {game.errors[0]}")
        variant = game.headers.get("Variant", "").strip().lower()
        if variant not in STANDARD_VARIANTS:
            raise PgnError(f"Only standard chess is supported (got variant {variant!r}).")
        board = game.board()
        start_fen = board.fen()
        moves: list[chess.Move] = []
        sans: list[str] = []
        clocks: list[float | None] = []
        for node in game.mainline():
            sans.append(board.san(node.move))
            board.push(node.move)
            moves.append(node.move)
            clocks.append(node.clock())
        if not moves:
            continue  # a header-only or unreadable game has nothing to review
        games.append(
            GameRecord(
                headers=dict(game.headers),
                start_fen=start_fen,
                moves=moves,
                sans=sans,
                clocks=clocks if any(c is not None for c in clocks) else [None] * len(moves),
            )
        )
    if not games:
        raise PgnError("No games with moves found — paste the full PGN, including the moves.")
    return games


def detect_user_color(game: GameRecord, usernames: list[str]) -> Color | None:
    names = {u.strip().lower() for u in usernames if u.strip()}
    if game.white.lower() in names:
        return "white"
    if game.black.lower() in names:
        return "black"
    return None
