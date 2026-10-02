"""Wiring shared by the CLI and the API: the database and engine pools."""

from __future__ import annotations

from chess_analysis_engine.config import data_dir, default_engines, find_stockfish
from chess_analysis_engine.engine.pool import EnginePool
from chess_analysis_engine.storage.db import Database


class EngineNotFound(RuntimeError):
    pass


ENGINE_HELP = (
    "Stockfish was not found. Run ./scripts/get_stockfish.sh, install it with "
    "`yay -S stockfish`, or point CAE_STOCKFISH_PATH at the binary."
)


def default_db() -> Database:
    return Database(data_dir() / "app.db")


def open_pool(db: Database | None = None, size: int | None = None, hash_mb: int | None = None) -> EnginePool:
    path = find_stockfish()
    if not path:
        raise EngineNotFound(ENGINE_HELP)
    return EnginePool(path, size or default_engines(), hash_mb or 64, db)
