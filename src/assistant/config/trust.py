"""Trust decisions for project-local packs.

A pack defines what may run on this machine and how risky it is claimed to be, so packs found in a
repository the user merely opened (``./.assistant/packs``) must not load until the user trusts that
directory. User-level packs and the builtin packs are always trusted.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class TrustStore:
    """Remembers which project directories the user trusts (JSON list in the data dir)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _read(self) -> set[str]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return set()
        except (OSError, ValueError) as exc:
            log.warning("ignoring unreadable trust file %s: %s", self._path, exc)
            return set()
        return {str(item) for item in data} if isinstance(data, list) else set()

    @staticmethod
    def _key(directory: Path) -> str:
        return str(directory.expanduser().resolve())

    def is_trusted(self, directory: Path) -> bool:
        return self._key(directory) in self._read()

    def trust(self, directory: Path) -> None:
        entries = self._read() | {self._key(directory)}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(sorted(entries), indent=2), encoding="utf-8")

    def revoke(self, directory: Path) -> bool:
        entries = self._read()
        key = self._key(directory)
        if key not in entries:
            return False
        entries.discard(key)
        self._path.write_text(json.dumps(sorted(entries), indent=2), encoding="utf-8")
        return True

    def all(self) -> list[str]:
        return sorted(self._read())
