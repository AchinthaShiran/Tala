# DevOps: v3-core

- Packaging: hatchling wheel; builtin packs and golden set ship as package data (verified by building the wheel). Console script `lpa`.
- CI (`.github/workflows/ci.yml`): matrix Ubuntu/Windows/macOS x Python 3.11/3.12: ruff check + format, mypy --strict, import-linter, `lpa packs validate --strict`, pytest with coverage, keyword-mode retrieval regression (`--min-recall 0.9`). No Ollama needed in CI (all model calls are scripted).
- Not yet done: release workflow (tag -> wheel/sdist -> PyPI), `pip-audit`, signed artifacts, a Windows installer/winget manifest.
- Rollback: users pin a version; data files are caches or append-only (index rebuildable, audit append-only, checkpoints owned by LangGraph).
- Local dev: `pip install -e ".[dev]"`; `ASSISTANT_HOME` isolates a dev profile.
