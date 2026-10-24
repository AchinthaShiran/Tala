# Changelog

## 3.0.0

Complete rebuild of the v2 prototype. See [docs/from-v2.md](docs/from-v2.md).

### Added
- LangChain + LangGraph agent: route, executor loop (bounded), authorize (interrupt), run, summarize.
- Pack format with logical tools, per-OS variants, typed parameters with constraints, conditional
  arguments, defaults, layered pack directories, strict loader and `tala packs validate`.
- 95 builtin tools: system, processes, network, files (cross-platform) plus git, docker, adb, fastboot,
  npm, winget, powercfg, schtasks, wevtutil.
- Hybrid tool retrieval (FTS5 BM25 + sqlite-vec, RRF) with confidence-driven routing.
- Safety: mandatory risk, policy engine, exact-command approval, untrusted-output fencing, audit log,
  bounded subprocess execution with tree kill.
- Session persistence (SQLite checkpoints), history budgeting, long-term facts.
- Typed event service API; Typer/rich CLI (`chat`, `ask`, `packs`, `facts`, `audit`, `doctor`, `eval`).
- Golden-set evaluation (retrieval and live agent), architecture contract tests, CI matrix.

### Removed
- `scrcpy_mirror`, `scrcpy_mirror_screen_off` (long-running GUI processes).
- The v2 `FileSystemGateway` (unused).
