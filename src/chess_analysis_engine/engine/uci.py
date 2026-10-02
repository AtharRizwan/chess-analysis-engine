"""Stockfish wrapper: MultiPV analysis of one position, cached in SQLite.

The engine gets the moves since the last capture or pawn move, so it can see repetitions,
and that same history is part of the cache key.
"""

from __future__ import annotations

import contextlib
import hashlib
import threading
from types import TracebackType

import chess
import chess.engine

from chess_analysis_engine.config import EngineSettings
from chess_analysis_engine.models import EngineLine, PositionEval, Score
from chess_analysis_engine.storage.db import Database

CACHE_VERSION = 1


def terminal_score(board: chess.Board) -> Score | None:
    """Score for a finished game (no engine needed), else None."""
    if board.is_checkmate():
        return Score(result="0-1" if board.turn == chess.WHITE else "1-0")
    if board.is_stalemate() or board.is_insufficient_material():
        return Score(result="1/2-1/2")
    if board.is_fivefold_repetition() or board.is_seventyfive_moves():
        return Score(result="1/2-1/2")
    return None


def score_from_engine(pov: chess.engine.PovScore) -> Score:
    white = pov.white()
    mate = white.mate()
    if mate is not None:
        if mate == 0:  # "mate 0": the side to move is already mated
            return Score(result="0-1" if pov.turn == chess.WHITE else "1-0")
        return Score(mate=mate)
    return Score(cp=white.score())


def line_from_moves(board: chess.Board, moves: list[chess.Move], score: Score, depth: int) -> EngineLine:
    """Build an EngineLine, stopping at the first illegal move (engines occasionally emit one)."""
    b = board.copy(stack=False)
    uci: list[str] = []
    san: list[str] = []
    for move in moves:
        if not b.is_legal(move):
            break
        san.append(b.san(move))
        uci.append(move.uci())
        b.push(move)
    return EngineLine(uci=uci, san=san, score=score, depth=depth)


def history_for_engine(board: chess.Board) -> chess.Board:
    """Copy of `board` keeping only the moves that matter for repetition detection."""
    keep = min(len(board.move_stack), board.halfmove_clock)
    return board.copy(stack=keep)


class Engine:
    """A single Stockfish process. Thread-safe (calls are serialized).

    Use one search thread per process: Stockfish's multi-threaded search combined with depth
    limits and MultiPV can occasionally take 100x longer on a re-searched position. Parallelism
    comes from `EnginePool` running several single-threaded engines on different positions.
    """

    def __init__(self, settings: EngineSettings, db: Database | None = None):
        self.settings = settings
        self.db = db
        self._engine = chess.engine.SimpleEngine.popen_uci(settings.path)
        self._engine.configure({"Threads": settings.threads, "Hash": settings.hash_mb})
        self.name: str = self._engine.id.get("name", "unknown engine")
        self._lock = threading.Lock()

    def close(self) -> None:
        with contextlib.suppress(chess.engine.EngineTerminatedError):
            self._engine.quit()

    def __enter__(self) -> Engine:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _cache_key(self, board: chess.Board, depth: int | None, nodes: int | None, multipv: int) -> str:
        history = history_for_engine(board)
        parts = [
            str(CACHE_VERSION),
            self.name,
            f"d{depth}",
            f"n{nodes}",
            f"m{multipv}",
            history.root().fen(),
            " ".join(m.uci() for m in history.move_stack),
        ]
        return hashlib.sha1("|".join(parts).encode()).hexdigest()

    def analyse(
        self,
        board: chess.Board,
        *,
        depth: int | None = None,
        nodes: int | None = None,
        multipv: int = 1,
        max_seconds: float | None = None,
    ) -> PositionEval:
        """Analyse `board` to `depth` (or `nodes`), stopping early after `max_seconds`."""
        terminal = terminal_score(board)
        if terminal is not None:
            return PositionEval(fen=board.fen(), score=terminal, engine=self.name)

        key = self._cache_key(board, depth, nodes, multipv)
        if self.db is not None and (cached := self.db.cache_get(key)) is not None:
            return PositionEval.model_validate_json(cached)

        limit = chess.engine.Limit(depth=depth, nodes=nodes, time=max_seconds)
        best_by_depth: list[tuple[int, str]] = []
        with self._lock, self._engine.analysis(history_for_engine(board), limit, multipv=multipv) as search:
            for info in search:
                pv = info.get("pv")
                if info.get("multipv", 1) != 1 or not pv or "depth" not in info:
                    continue
                entry = (info["depth"], pv[0].uci())
                if best_by_depth and best_by_depth[-1][0] == entry[0]:
                    best_by_depth[-1] = entry
                else:
                    best_by_depth.append(entry)
            infos = list(search.multipv)

        lines = [
            line_from_moves(board, info["pv"], score_from_engine(info["score"]), info.get("depth", 0))
            for info in infos
            if info.get("pv") and "score" in info
        ]
        lines = [line for line in lines if line.uci]
        result = PositionEval(
            fen=board.fen(),
            score=lines[0].score if lines else Score(cp=0),
            lines=lines,
            depth=max((line.depth for line in lines), default=0),
            engine=self.name,
            best_by_depth=best_by_depth,
        )
        # A search cut short by the time cap isn't the result we were asked for: don't cache it.
        if self.db is not None and (depth is None or result.depth >= depth):
            self.db.cache_put(key, result.model_dump_json())
        return result
