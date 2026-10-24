# Changelog

## 3.0.1

### Added
- About 100 more built-in tools (about 200 in total): file reading, searching, hashing, copying and
  archiving; Python/pip/uv, Java/Maven/Gradle, Node/Yarn/pnpm, .NET, Go, Rust and Ruby; curl, port checks,
  Wi-Fi and DNS; SSH; firewall; services; apt, Homebrew and Chocolatey; system logs; GitHub CLI; more git.
- Summary-first output for content-heavy tools (web pages, files, logs, diffs): the reply ends with an offer
  of the original output, which a "yes" shows verbatim (pack key `offer_original`, setting
  `runtime.offer_original_output`).

### Fixed
- `install.ps1` no longer rejects the `py` launcher installed by the Python install manager, and no longer
  hangs on Python launchers that wait for input. Its error now lists the interpreters it checked.
- Retrieval evaluation skips cases whose tools do not exist on the current OS, so the quality gate is
  stable on Linux and macOS.
- Tests no longer fail on Python builds without SQLite extension loading, or when long paths wrap console output.

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
- Summary-first output for content-heavy tools (web pages, files, logs, diffs): the reply ends with an offer
  of the original output, which a "yes" shows verbatim (pack key `offer_original`, setting
  `runtime.offer_original_output`).
- Hybrid tool retrieval (FTS5 BM25 + sqlite-vec, RRF) with confidence-driven routing.
- Safety: mandatory risk, policy engine, exact-command approval, untrusted-output fencing, audit log,
  bounded subprocess execution with tree kill.
- Session persistence (SQLite checkpoints), history budgeting, long-term facts.
- Typed event service API; Typer/rich CLI (`chat`, `ask`, `packs`, `facts`, `audit`, `doctor`, `eval`).
- Golden-set evaluation (retrieval and live agent), architecture contract tests, CI matrix.

### Removed
- `scrcpy_mirror`, `scrcpy_mirror_screen_off` (long-running GUI processes).
- The v2 `FileSystemGateway` (unused).
