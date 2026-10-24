# Changelog

## 3.0.0

Complete rebuild of the v2 prototype. See [docs/from-v2.md](docs/from-v2.md).

### Added
- One-line installers (`install.ps1`, `install.sh`) and a first-run setup wizard (`tala setup`):
  hardware detection, default or advanced setup from a curated model catalog, memory estimates,
  resource warnings, safe config merging with backup, and guided model downloads.
- LangChain + LangGraph agent: route, executor loop (bounded), authorize (interrupt), run, summarize.
- Pack format with logical tools, per-OS variants, typed parameters with constraints, conditional
  arguments, defaults, layered pack directories, strict loader and `tala packs validate`.
- About 200 builtin tools: system, processes, network and files (cross-platform) plus git (and GitHub CLI),
  docker, adb, fastboot, Python/pip/uv, Java/Maven/Gradle, Node/Yarn/pnpm, .NET/Go/Rust/Ruby, curl, SSH,
  firewall, services, apt/Homebrew/Chocolatey, system logs, file reading, searching, hashing, copying
  and archiving, and winget, powercfg, schtasks and wevtutil on Windows.
- Hybrid tool retrieval (FTS5 BM25 + sqlite-vec, RRF) with confidence-driven routing.
- Safety: mandatory risk, policy engine, exact-command approval, untrusted-output fencing, audit log,
  bounded subprocess execution with tree kill.
- Session persistence (SQLite checkpoints), history budgeting, long-term facts.
- Typed event service API; Typer/rich CLI (`chat`, `ask`, `packs`, `facts`, `audit`, `doctor`, `eval`).
- Golden-set evaluation (retrieval and live agent), architecture contract tests, CI matrix.

### Removed
- `scrcpy_mirror`, `scrcpy_mirror_screen_off` (long-running GUI processes).
- The v2 `FileSystemGateway` (unused).
