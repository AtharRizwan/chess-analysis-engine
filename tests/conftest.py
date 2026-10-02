from __future__ import annotations

from pathlib import Path

import pytest

from chess_analysis_engine.config import find_stockfish
from chess_analysis_engine.engine.pool import EnginePool
from chess_analysis_engine.storage.db import Database

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture(scope="session")
def pool():
    """Two single-threaded engines; engine tests are skipped when Stockfish is missing."""
    path = find_stockfish()
    if not path:
        pytest.skip("Stockfish not installed")
    with EnginePool(path, size=2, hash_mb=32) as engines:
        yield engines
