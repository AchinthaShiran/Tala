"""Filesystem locations (platform-appropriate, overridable for tests and portable installs)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path, user_data_path

APP_NAME = "local-assistant"
HOME_ENV = "ASSISTANT_HOME"


@dataclass(frozen=True, slots=True)
class AppPaths:
    config_dir: Path
    data_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.yaml"

    @property
    def user_packs_dir(self) -> Path:
        return self.config_dir / "packs"

    @property
    def checkpoints_db(self) -> Path:
        return self.data_dir / "checkpoints.sqlite"

    @property
    def index_db(self) -> Path:
        return self.data_dir / "tool_index.sqlite"

    @property
    def facts_db(self) -> Path:
        return self.data_dir / "facts.sqlite"

    @property
    def trusted_projects(self) -> Path:
        return self.data_dir / "trusted_projects.json"

    @property
    def audit_log(self) -> Path:
        return self.data_dir / "audit.jsonl"

    def ensure(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)


def default_paths(data_dir_override: Path | None = None) -> AppPaths:
    """``$ASSISTANT_HOME`` wins, then the platform config/data directories."""
    home = os.environ.get(HOME_ENV)
    if home:
        root = Path(home)
        return AppPaths(root / "config", data_dir_override or root / "data")
    return AppPaths(
        user_config_path(APP_NAME, appauthor=False),
        data_dir_override or user_data_path(APP_NAME, appauthor=False),
    )


def builtin_packs_dir() -> Path:
    """Packs shipped inside the wheel."""
    return Path(__file__).resolve().parent.parent / "builtin_packs"


def project_packs_dir(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / ".assistant" / "packs"
