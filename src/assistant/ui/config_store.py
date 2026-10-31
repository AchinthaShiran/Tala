"""Reading and writing ``config.yaml`` for the settings page (no Qt, so it is unit-testable).

Only values the user actually changed are written, as dotted paths (``"runtime.max_steps"``), so the
file stays small and new defaults keep flowing in. Every save is validated first and the previous file
is kept as ``config.yaml.bak``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from assistant.config import Settings, load_settings
from assistant.domain import ConfigError

HEADER = "# Written by the settings page. Safe to edit; only values you changed are listed.\n"


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def backup_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".bak")

    def load(self) -> Settings:
        """Effective settings: defaults < file < environment (what the assistant really uses)."""
        return load_settings(self.path)

    def save(self, changes: Mapping[str, Any]) -> bool:
        """Apply dotted-path ``changes``. Raises ``ConfigError`` (file untouched) if invalid.

        A dict value replaces the whole dict at that path, which is how entries get removed.
        Returns True when the file was written.
        """
        if not changes:
            return False
        document = self._read()
        for dotted, value in changes.items():
            _set(document, dotted.split("."), value)
        # Validate the result on its own (no environment), exactly as it will be loaded later.
        load_settings(None, env={}, overrides=document)
        self._write(document)
        return True

    def reset(self) -> bool:
        """Delete the file (keeping a backup), returning to built-in defaults."""
        if not self.path.exists():
            return False
        self.backup_path.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
        self.path.unlink()
        return True

    # -- internals ---------------------------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            loaded = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"cannot read config {self.path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError(f"config {self.path} must be a mapping at top level")
        return loaded

    def _write(self, document: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.backup_path.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
        text = HEADER + yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
        self.path.write_text(text, encoding="utf-8")


def _set(document: dict[str, Any], keys: list[str], value: Any) -> None:
    node = document
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = node[key] = {}
        node = child
    node[keys[-1]] = value


def dig(document: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    """Read a dotted path from a nested mapping."""
    node: Any = document
    for key in dotted.split("."):
        if not isinstance(node, Mapping) or key not in node:
            return default
        node = node[key]
    return default if node is None else node
