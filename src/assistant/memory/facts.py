"""Long-term user facts ("my phone is at 192.168.1.20") injected into the system prompt."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path


class FactStore:
    """Tiny key/value store, independent of any chat session."""

    def __init__(self, db_path: Path | str) -> None:
        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS facts ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL, updated TEXT NOT NULL)"
            )

    def remember(self, key: str, value: str) -> None:
        key = key.strip().lower()
        if not key or not value.strip():
            raise ValueError("fact key and value must not be empty")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO facts(key, value, updated) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated = excluded.updated",
                (key, value.strip(), datetime.now(UTC).isoformat(timespec="seconds")),
            )

    def forget(self, key: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM facts WHERE key = ?", (key.strip().lower(),))
        return cursor.rowcount > 0

    def all(self) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM facts ORDER BY key").fetchall()
        return dict(rows)

    def render(self, max_chars: int = 1200) -> str:
        """Prompt section listing facts, newest data first-class but capped in size."""
        lines: list[str] = []
        used = 0
        for key, value in self.all().items():
            line = f"- {key}: {value}"
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
