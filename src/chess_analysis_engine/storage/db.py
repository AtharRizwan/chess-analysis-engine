"""SQLite storage: imported games, reviews, the engine cache and learning data.

One connection per thread (SQLite connections can't be shared across threads), WAL mode so
the analysis worker and API requests don't block each other.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    # 1 — core tables
    """
    CREATE TABLE engine_cache (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE games (
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,            -- pgn | chesscom | lichess
        source_id TEXT NOT NULL,         -- chess.com uuid, lichess id, or a hash of the PGN
        url TEXT,
        white TEXT,
        black TEXT,
        white_rating INTEGER,
        black_rating INTEGER,
        result TEXT,
        time_class TEXT,
        time_control TEXT,
        played_at TEXT,
        user_color TEXT,                 -- white | black | NULL when unknown
        pgn TEXT NOT NULL,
        imported_at TEXT NOT NULL,
        UNIQUE (source, source_id)
    );
    CREATE TABLE reviews (
        game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
        preset TEXT NOT NULL,
        status TEXT NOT NULL,            -- queued | running | done | error
        payload TEXT,                    -- GameReview JSON
        error TEXT,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    # 2 — endgame tablebase answers (lichess API), keyed by position
    """
    CREATE TABLE tablebase_cache (
        fen TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    # 3 — the learning loop: per-move index for cross-game insights, per-game stats, drills
    """
    CREATE TABLE move_index (
        game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
        ply INTEGER NOT NULL,
        color TEXT NOT NULL,
        is_user INTEGER NOT NULL,
        classification TEXT NOT NULL,
        ep_loss REAL NOT NULL,
        accuracy REAL NOT NULL,
        phase TEXT NOT NULL,
        cause TEXT,                      -- leading fact behind a costly move
        motif TEXT,
        spent REAL,                      -- seconds on the clock for this move
        PRIMARY KEY (game_id, ply)
    );
    CREATE TABLE review_stats (
        game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
        user_color TEXT,
        accuracy REAL,
        played_at TEXT,
        indexed_at TEXT NOT NULL
    );
    CREATE TABLE drills (
        id INTEGER PRIMARY KEY,
        game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
        ply INTEGER NOT NULL,
        start_fen TEXT NOT NULL,
        moves TEXT NOT NULL,             -- JSON: UCI moves from start_fen to the drill position
        fen TEXT NOT NULL,               -- the drill position
        color TEXT NOT NULL,             -- side to move (yours)
        played TEXT NOT NULL,            -- what you played in the game (SAN)
        best TEXT NOT NULL,              -- the engine's move (SAN)
        accepted TEXT NOT NULL,          -- JSON: UCI moves that solve it
        themes TEXT NOT NULL,            -- JSON: cause and motif tags
        payload TEXT NOT NULL,           -- the move's review (MoveReview JSON): hints and the answer
        box INTEGER NOT NULL DEFAULT 1,  -- Leitner box 1..5
        due_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        solved INTEGER NOT NULL DEFAULT 0,
        last_result TEXT,
        created_at TEXT NOT NULL,
        UNIQUE (game_id, ply)
    );
    CREATE INDEX drills_due ON drills (due_at);
    """,
    # 4 — remember which version of the review format a stored review uses
    """
    ALTER TABLE reviews ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
    """,
    # 5 — the optional Claude coach: narrations it wrote (or the template fallback) and what each call cost
    """
    CREATE TABLE narrations (
        key TEXT PRIMARY KEY,
        model TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE coach_usage (
        id INTEGER PRIMARY KEY,
        model TEXT NOT NULL,
        outcome TEXT NOT NULL,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        cache_read_tokens INTEGER NOT NULL DEFAULT 0,
        cache_write_tokens INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """,
    # 6 — how each coach call was made: the API (billed per token) or Claude Code (the user's Claude plan)
    """
    ALTER TABLE coach_usage ADD COLUMN backend TEXT NOT NULL DEFAULT 'api';
    """,
]


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._local = threading.local()
        self._migrate()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")

    def _migrate(self) -> None:
        conn = self.conn
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")

    # --- engine cache ---------------------------------------------------------------------

    def cache_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM engine_cache WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def cache_put(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO engine_cache (key, value, created_at) VALUES (?, ?, ?)",
            (key, value, utcnow()),
        )

    def tablebase_get(self, fen: str) -> str | None:
        row = self.conn.execute("SELECT value FROM tablebase_cache WHERE fen = ?", (fen,)).fetchone()
        return row["value"] if row else None

    def tablebase_put(self, fen: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO tablebase_cache (fen, value, created_at) VALUES (?, ?, ?)",
            (fen, value, utcnow()),
        )

    # --- games ----------------------------------------------------------------------------

    def upsert_game(self, game: dict[str, Any]) -> tuple[int, bool]:
        """Insert a game unless (source, source_id) exists. Returns (id, created)."""
        row = self.conn.execute(
            "SELECT id FROM games WHERE source = ? AND source_id = ?",
            (game["source"], game["source_id"]),
        ).fetchone()
        if row:
            return row["id"], False
        columns = [
            "source", "source_id", "url", "white", "black", "white_rating", "black_rating",
            "result", "time_class", "time_control", "played_at", "user_color", "pgn",
        ]  # fmt: skip
        values = [game.get(c) for c in columns] + [utcnow()]
        cursor = self.conn.execute(
            f"INSERT INTO games ({', '.join(columns)}, imported_at) "
            f"VALUES ({', '.join('?' * (len(columns) + 1))})",
            values,
        )
        return int(cursor.lastrowid or 0), True

    def get_game(self, game_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        return dict(row) if row else None

    def list_games(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT g.*, r.status AS review_status, r.preset AS review_preset, r.version AS review_version
            FROM games g LEFT JOIN reviews r ON r.game_id = g.id
            ORDER BY COALESCE(g.played_at, g.imported_at) DESC, g.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_user_color(self, game_id: int, color: str | None) -> None:
        self.conn.execute("UPDATE games SET user_color = ? WHERE id = ?", (color, game_id))

    # --- reviews --------------------------------------------------------------------------

    def save_review(
        self,
        game_id: int,
        preset: str,
        status: str,
        payload: str | None = None,
        error: str | None = None,
        version: int | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO reviews (game_id, preset, status, payload, error, updated_at, version)
            VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, 1))
            ON CONFLICT (game_id) DO UPDATE SET
                preset = excluded.preset, status = excluded.status,
                payload = COALESCE(excluded.payload, reviews.payload),
                error = excluded.error, updated_at = excluded.updated_at,
                version = COALESCE(?, reviews.version)
            """,
            (game_id, preset, status, payload, error, utcnow(), version, version),
        )

    def forget_review(self, game_id: int) -> None:
        """Drop a game's review and everything learned from it (e.g. after changing your side)."""
        with self.transaction() as conn:
            for table in ("reviews", "move_index", "review_stats", "drills"):
                conn.execute(f"DELETE FROM {table} WHERE game_id = ?", (game_id,))

    def get_review(self, game_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM reviews WHERE game_id = ?", (game_id,)).fetchone()
        return dict(row) if row else None

    # --- learning: move index, review stats, drills ----------------------------------------

    def index_review(self, game_id: int, stats: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM move_index WHERE game_id = ?", (game_id,))
            if rows:
                columns = list(rows[0])
                conn.executemany(
                    f"INSERT INTO move_index ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                    [[row[c] for c in columns] for row in rows],
                )
            conn.execute(
                "INSERT OR REPLACE INTO review_stats (game_id, user_color, accuracy, played_at, indexed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (game_id, stats.get("user_color"), stats.get("accuracy"), stats.get("played_at"), utcnow()),
            )

    def unindexed_reviews(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT r.game_id, r.payload, g.played_at FROM reviews r JOIN games g ON g.id = r.game_id
            LEFT JOIN review_stats s ON s.game_id = r.game_id
            WHERE r.status = 'done' AND r.payload IS NOT NULL
              AND (s.game_id IS NULL OR s.indexed_at < r.updated_at)
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def user_moves(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT m.*, g.white, g.black, g.played_at FROM move_index m JOIN games g ON g.id = m.game_id
            WHERE m.is_user = 1
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def review_stats(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT s.*, g.white, g.black, g.result FROM review_stats s JOIN games g ON g.id = s.game_id "
            "WHERE s.user_color IS NOT NULL ORDER BY COALESCE(s.played_at, s.indexed_at)"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_drill(self, drill: dict[str, Any]) -> None:
        """Insert a drill, or refresh its content after a re-review (keeping its schedule)."""
        columns = list(drill)
        content = ["start_fen", "moves", "fen", "color", "played", "best", "accepted", "themes", "payload"]
        self.conn.execute(
            f"INSERT INTO drills ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))}) "
            f"ON CONFLICT (game_id, ply) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in content)}",
            [drill[c] for c in columns],
        )

    def prune_drills(self, game_id: int, keep_plies: list[int]) -> None:
        """Drop a game's drills for moves that are no longer mistakes after a re-review."""
        marks = ", ".join("?" * len(keep_plies)) or "NULL"
        self.conn.execute(
            f"DELETE FROM drills WHERE game_id = ? AND ply NOT IN ({marks})", [game_id, *keep_plies]
        )

    def due_drills(self, now: str, limit: int = 20, theme: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM drills WHERE due_at <= ?"
        params: list[Any] = [now]
        if theme:
            query += " AND themes LIKE ?"
            params.append(f'%"{theme}"%')
        query += " ORDER BY box, due_at LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(query, params).fetchall()]

    def drills_for_game(self, game_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM drills WHERE game_id = ? ORDER BY ply", (game_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_drill(self, drill_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM drills WHERE id = ?", (drill_id,)).fetchone()
        return dict(row) if row else None

    def update_drill(self, drill_id: int, **fields: Any) -> None:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE drills SET {assignments} WHERE id = ?", [*fields.values(), drill_id])

    def drill_counts(self, now: str) -> dict[str, Any]:
        rows = self.conn.execute("SELECT box, COUNT(*) AS n FROM drills GROUP BY box").fetchall()
        due = self.conn.execute("SELECT COUNT(*) FROM drills WHERE due_at <= ?", (now,)).fetchone()[0]
        return {
            "due": due,
            "boxes": {str(r["box"]): r["n"] for r in rows},
            "total": sum(r["n"] for r in rows),
        }

    # --- coach --------------------------------------------------------------------------

    def narration_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT payload FROM narrations WHERE key = ?", (key,)).fetchone()
        return row["payload"] if row else None

    def narration_put(self, key: str, model: str, payload: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO narrations (key, model, payload, created_at) VALUES (?, ?, ?, ?)",
            (key, model, payload, utcnow()),
        )

    def log_coach_usage(self, model: str, outcome: str, usage: dict[str, int], backend: str = "api") -> None:
        self.conn.execute(
            """INSERT INTO coach_usage (backend, model, outcome, input_tokens, output_tokens,
                   cache_read_tokens, cache_write_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                backend,
                model,
                outcome,
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                usage.get("cache_read_tokens", 0),
                usage.get("cache_write_tokens", 0),
                utcnow(),
            ),
        )

    def coach_usage(self) -> list[dict[str, Any]]:
        """Totals per backend and model: calls, narrations rejected by the checks, and tokens."""
        rows = self.conn.execute(
            """SELECT backend, model, COUNT(*) AS calls, SUM(outcome != 'ok') AS rejected,
                   SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
                   SUM(cache_read_tokens) AS cache_read_tokens, SUM(cache_write_tokens) AS cache_write_tokens
               FROM coach_usage GROUP BY backend, model ORDER BY backend, model"""
        ).fetchall()
        return [dict(r) for r in rows]

    # --- settings -------------------------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value))
        )
