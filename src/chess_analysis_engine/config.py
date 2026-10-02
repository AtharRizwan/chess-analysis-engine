"""Runtime configuration: engine discovery, analysis presets and the data directory."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
RESOURCES_DIR = PACKAGE_DIR / "resources"
# Only meaningful when running from a source checkout (where ./bin/stockfish lives).
REPO_ROOT = PACKAGE_DIR.parents[1]


@dataclass(frozen=True)
class Preset:
    """How hard the engine looks at each position."""

    name: str
    depth: int
    # Safety cap per position; a handful of positions search far longer than the rest.
    max_seconds: float
    multipv: int = 3
    # Critical moves (mistakes, only-moves, sacrifices) are re-checked deeper.
    critical_depth_bonus: int = 4
    critical_multipv: int = 3

    @property
    def critical_depth(self) -> int:
        return self.depth + self.critical_depth_bonus

    @property
    def critical_max_seconds(self) -> float:
        return self.max_seconds * 3


PRESETS: dict[str, Preset] = {
    "quick": Preset("quick", depth=14, max_seconds=2.0),
    "standard": Preset("standard", depth=18, max_seconds=6.0),
    "deep": Preset("deep", depth=22, max_seconds=20.0),
}


def default_engines() -> int:
    """How many single-threaded engines to run: leave a couple of cores for everything else."""
    return max(1, min(8, (os.cpu_count() or 2) - 2))


@dataclass(frozen=True)
class EngineSettings:
    path: str
    threads: int = 1
    hash_mb: int = 64


def find_stockfish() -> str | None:
    """Locate Stockfish: $CAE_STOCKFISH_PATH, then ./bin/stockfish in the checkout, then PATH."""
    env = os.environ.get("CAE_STOCKFISH_PATH")
    if env:
        return env
    local = REPO_ROOT / "bin" / "stockfish"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which("stockfish")


def data_dir() -> Path:
    """Directory for the SQLite database and caches ($CAE_DATA_DIR, else the XDG data dir)."""
    env = os.environ.get("CAE_DATA_DIR")
    if env:
        path = Path(env)
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / "chess-analysis-engine"
    path.mkdir(parents=True, exist_ok=True)
    return path
