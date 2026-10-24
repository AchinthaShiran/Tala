"""Layering is a tested property, not a convention (ADR-005)."""

from __future__ import annotations

from pathlib import Path

from importlinter.cli import lint_imports

ROOT = Path(__file__).resolve().parent.parent


def test_import_linter_contracts_hold(monkeypatch):
    monkeypatch.chdir(ROOT)
    assert lint_imports(config_filename=str(ROOT / "pyproject.toml")) == 0
