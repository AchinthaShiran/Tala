"""Applying the wizard's result: write the config file and download missing models."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol

import yaml

from assistant.config import Settings

HEADER = "# Written by the setup wizard. Safe to edit; only values that differ from defaults are listed.\n"

Progress = Callable[[str, int | None, int | None], None]  # status, total bytes, completed bytes


class OllamaLike(Protocol):
    def list(self) -> Any: ...
    def pull(self, model: str, *, stream: bool) -> Iterable[Any]: ...


def write_config(path: Path, overrides: dict[str, Any]) -> Path | None:
    """Merge ``overrides`` into the config file. Returns the backup path if one was made."""
    existing: dict[str, Any] = {}
    backup: Path | None = None
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            existing = loaded
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    merged = _merge(existing, overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        HEADER + yaml.safe_dump(merged, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return backup


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def needed_tags(settings: Settings) -> list[str]:
    """Every model the configuration will actually use, without duplicates."""
    tags = [settings.models[a.model].name for a in settings.agents.values()]
    if settings.embeddings is not None and settings.retrieval.use_embeddings:
        tags.append(settings.embeddings.name)
    return list(dict.fromkeys(tags))


def installed_tags(client: OllamaLike) -> set[str]:
    return {m.model or "" for m in client.list().models}


def missing_tags(wanted: Iterable[str], installed: set[str]) -> list[str]:
    def present(tag: str) -> bool:
        return tag in installed or (":" not in tag and f"{tag}:latest" in installed)

    return [tag for tag in wanted if not present(tag)]


def pull_model(client: OllamaLike, tag: str, on_progress: Progress) -> None:
    """Download one model, reporting progress. Raises if Ollama reports an error."""
    for chunk in client.pull(tag, stream=True):
        on_progress(getattr(chunk, "status", "") or "", chunk.total, chunk.completed)
