"""Problems found while loading or linting packs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class PackIssue:
    severity: Severity
    message: str
    file: str = ""
    tool: str | None = None

    def __str__(self) -> str:
        where = self.file + (f" :: {self.tool}" if self.tool else "")
        return (
            f"[{self.severity.value}] {where}: {self.message}"
            if where
            else (f"[{self.severity.value}] {self.message}")
        )
