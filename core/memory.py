"""
Long-term memory (spec section 18). SQLite for Phase 1; the schema is
intentionally simple key/value + event log so migrating to
Postgres/pgvector later is a storage-layer swap, not a rewrite.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from core.config import get_config
from core.logging_setup import get_logger

log = get_logger()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    outcome TEXT NOT NULL,       -- 'success' | 'failed' | 'cancelled'
    detail TEXT,
    created_at REAL NOT NULL
);
"""


class Memory:
    def __init__(self) -> None:
        db_path = get_config().resolved_db_path()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        finally:
            cur.close()

    # ---- preferences (long-term) ----

    def set_preference(self, key: str, value: Any) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value), time.time()),
            )

    def get_preference(self, key: str, default: Optional[Any] = None) -> Any:
        with self._cursor() as cur:
            cur.execute("SELECT value FROM preferences WHERE key = ?", (key,))
            row = cur.fetchone()
        return json.loads(row[0]) if row else default

    # ---- task history ----

    def log_task(self, command: str, outcome: str, detail: str = "") -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO task_history (command, outcome, detail, created_at) VALUES (?, ?, ?, ?)",
                (command, outcome, detail, time.time()),
            )

    def recent_tasks(self, limit: int = 20) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT command, outcome, detail, created_at FROM task_history "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        return [
            {"command": c, "outcome": o, "detail": d, "created_at": t}
            for c, o, d, t in rows
        ]

    def close(self) -> None:
        self._conn.close()
