"""Append-only audit trail of every tool decision and execution."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AuditEntry:
    session: str
    tool: str
    argv: tuple[str, ...]
    mode: str  # approval mode applied
    approved_by: str  # auto | user | denied | policy
    status: str  # ok | error | timeout | denied
    exit_code: int | None = None
    duration_ms: int = 0
    truncated: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class AuditLog(Protocol):
    def record(self, entry: AuditEntry) -> None: ...


class NullAuditLog:
    def record(self, entry: AuditEntry) -> None:
        return None


class JsonlAuditLog:
    """One JSON object per line; safe for concurrent writers within the process."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def record(self, entry: AuditEntry) -> None:
        line = json.dumps(asdict(entry), ensure_ascii=False)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
