"""Durable LangGraph session state."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def open_checkpointer(path: Path) -> SqliteSaver:
    """SQLite-backed checkpointer; sessions survive restarts and can be resumed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), check_same_thread=False)
    return SqliteSaver(connection)
