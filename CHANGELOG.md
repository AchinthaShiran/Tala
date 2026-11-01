# Changelog

## Unreleased

### Added
- The pet watches the battery (laptops): when it is low and unplugged it looks tired (heavy eyelids, yawns,
  a sweat drop and a pulsing battery icon); plugging in makes it cheerful with sparks. A speech bubble
  announces low or critical battery, charging, unplugging and full. Turn it off from the right-click menu
  (Battery alerts). Replies and approval requests now also appear in that bubble when the chat is closed.
- Pet size: choose Tiny (70 px) to Extra large (200 px) in Settings → Pet. The default is now Small (95 px);
  the pet resizes in place and the choice is remembered.

### Fixed
- A tool's output sent to the model is now also limited to what fits the model's context window (about
  0.8 characters per token). Long, symbol-heavy output such as a `tree` listing could overflow a small
  `num_ctx`, which made the server cut off the start of the prompt (the instructions) and the model
  answer without them.

### Added
- Eight built-in pet characters to choose in Settings → Pet: Nexo, Kiko, Momo, Lumi, ZEN, Owlly, Slimey and
  PupBot (plus the original robot). All follow the pointer and show every emotion.
- Smoother pet animation: 40 frames per second with frame-rate independent timing, expressions cross-fade,
  blinks close the eyelids gradually, the mood light glides between colours and the body breathes. The chat
  window fades in and out and glides to new messages (and stops following when you scroll up).
- Custom pet characters: put one transparent image per expression in `<config>/characters/<name>/` (only
  `neutral.png` is required; missing expressions fall back to the closest one) and choose it in
  Settings → Pet. "Create an example to edit" writes a complete template. See docs/characters.md.
- The desktop pet is now interactive and has emotions. Its eyes and head follow the mouse pointer anywhere on
  screen; it notices you arriving, falls in love if you keep the pointer on it, hops when clicked, is
  surprised when picked up, happy when put down and dizzy if shaken, and gets sleepy and falls asleep when
  ignored. It is happy after a reply, sad after an error and curious while it waits for your approval.
- Desktop pet (`tala ui`, or `tala-ui` with no console window): a small animated, always-on-top character
  you drag anywhere and click to chat. Replies stream into the chat, tool calls show as they run, and
  commands that need approval appear as cards with the exact command (Deny is the default; destructive tools
  need their name typed). It shows its mood (working, replying, waiting for you), badges itself when it needs
  you while the chat is closed, and lives in the system tray. Optional extra: `pip install "tala-ai[ui]"`.
- Settings window for the desktop pet (gear in the chat header, or right-click the pet): Ollama address
  with a live connection check, model pickers that show what is downloaded (with a download button),
  behaviour, safety levels in plain words, a searchable list of every tool (switch it off or change its
  approval), saved facts, and shortcuts to the config, packs and data folders. Saving writes only what you
  changed to `config.yaml` (keeping a `.bak`), rejects invalid values, and restarts the assistant.

## 3.0.2

### Fixed
- The release workflow no longer fails when a GitHub release for the tag already exists: it attaches the
  build files and installers to it instead of trying to create it again.

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
