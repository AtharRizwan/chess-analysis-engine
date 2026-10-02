"""A pool of single-threaded Stockfish processes analysing positions in parallel."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType

import chess

from chess_analysis_engine.config import EngineSettings
from chess_analysis_engine.engine.uci import Engine
from chess_analysis_engine.models import PositionEval
from chess_analysis_engine.storage.db import Database

# Neighbouring positions analysed by the same engine reuse its hash table.
CHUNK = 4


@dataclass(frozen=True)
class Request:
    board: chess.Board
    depth: int
    multipv: int = 1
    max_seconds: float | None = None


class EnginePool:
    def __init__(self, path: str, size: int, hash_mb: int = 64, db: Database | None = None):
        settings = EngineSettings(path=path, threads=1, hash_mb=hash_mb)
        with ThreadPoolExecutor(max(1, size)) as starter:
            self._engines = list(starter.map(lambda _: Engine(settings, db), range(max(1, size))))
        self.size = len(self._engines)
        self.name = self._engines[0].name
        self._idle: queue.Queue[Engine] = queue.Queue()
        for engine in self._engines:
            self._idle.put(engine)

    def close(self) -> None:
        for engine in self._engines:
            engine.close()

    def __enter__(self) -> EnginePool:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @contextmanager
    def engine(self) -> Iterator[Engine]:
        engine = self._idle.get()
        try:
            yield engine
        finally:
            self._idle.put(engine)

    def analyse(
        self,
        board: chess.Board,
        *,
        depth: int,
        multipv: int = 1,
        max_seconds: float | None = None,
    ) -> PositionEval:
        with self.engine() as engine:
            return engine.analyse(board, depth=depth, multipv=multipv, max_seconds=max_seconds)

    def analyse_many(
        self,
        requests: list[Request],
        on_done: Callable[[int, int], None] | None = None,
    ) -> list[PositionEval]:
        """Analyse all requests in parallel; results come back in request order.

        Requests are split into small contiguous chunks, each handled by one engine in order,
        so put them in the order you want a single engine to see them (e.g. last move first).
        """
        results: list[PositionEval | None] = [None] * len(requests)
        chunks = [range(i, min(i + CHUNK, len(requests))) for i in range(0, len(requests), CHUNK)]
        lock = threading.Lock()
        finished = 0

        def work(indices: range) -> None:
            nonlocal finished
            with self.engine() as engine:
                for k in indices:
                    r = requests[k]
                    results[k] = engine.analyse(
                        r.board, depth=r.depth, multipv=r.multipv, max_seconds=r.max_seconds
                    )
                    with lock:
                        finished += 1
                        if on_done is not None:
                            on_done(finished, len(requests))

        with ThreadPoolExecutor(self.size) as workers:
            for future in [workers.submit(work, chunk) for chunk in chunks]:
                future.result()
        return [r for r in results if r is not None]
