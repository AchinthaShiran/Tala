# Staff Engineer: v3-core
Standards: ruff (E,F,I,N,W,B,UP,SIM,S), mypy --strict, pytest, 100% typed public API, pydantic v2 frozen models, Protocols at boundaries, no bare except, no print in library code (logging), import-linter contracts, conventional commits.
Cross-cutting: logging via stdlib logger 'assistant.*', errors derive from AssistantError, settings injected not global.
