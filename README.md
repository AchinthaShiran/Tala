# Tala

A local, OS-agnostic AI assistant for your PC. Chat in plain language; a local model (via
[Ollama](https://ollama.com)) picks and runs **tools** defined in simple YAML files called **packs**.
Nothing leaves your machine, and nothing risky runs without your approval.

```
You: how much free disk space do I have?
→ disk_free (read_only)  powershell -NoProfile ... Get-PSDrive ...
  ✓ disk_free · 1093 ms
Assistant: Drive C has 9.2 GB free and drive D has 66.9 GB free.

You: stop the docker container web
╭──────────── Approval needed ────────────╮
│ docker_stop  mutating                   │
│ command: /usr/bin/docker stop web       │
╰─────────────────────────────────────────╯
Run it? [y/N]
```

## Why it is built this way

| Goal | How |
| --- | --- |
| **Add capabilities with YAML only** | Drop a file in a pack directory. No Python, no restart of design. See [pack authoring](docs/pack-authoring.md). |
| **Works on Windows, Linux and macOS** | One *logical* tool (`ping_host`) with per-OS command variants. Tools whose executable is missing are never offered to the model. |
| **Safe by default** | Mandatory risk level per tool, approval policy, exact command shown, no shell, argument constraints, untrusted-output fencing, audit log. See [safety](docs/safety.md). |
| **Runs on small local models** | Hybrid keyword + vector tool retrieval offers the model 4-8 tools instead of 100; arguments are validated and repaired; chat never loads the tool machinery. |
| **Engineered to grow** | LangChain + LangGraph agent, typed event API for any front end, layered architecture enforced by tests. See [architecture](docs/architecture.md). |

## Quick start

You need [Ollama](https://ollama.com/download) running locally.

**One-line install** (installs into an isolated environment, then starts the setup wizard):

```powershell
irm https://raw.githubusercontent.com/AchinthaShiran/Tala/main/install.ps1 | iex   # Windows
```

```sh
curl -fsSL https://raw.githubusercontent.com/AchinthaShiran/Tala/main/install.sh | sh   # macOS / Linux
```

**Or from PyPI** (needs Python 3.11 or newer, not a specific version):

```sh
pipx install tala-ai      # or: uv tool install tala-ai
tala setup
```

**From a clone:**

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
tala setup           # pick Default or Advanced; detects your hardware and warns about heavy models
tala chat            # start talking
```

`tala setup` offers three setups: **Default** (one fixed, conservative configuration, the same everywhere),
**Recommended** (tailored to your detected hardware) and **Advanced** (choose models, context size, memory
use, approval rules and speed options from curated sets, with warnings when a choice will strain your
machine). Whichever you pick, the full settings are shown and you confirm before anything is applied. It
also offers itself the first time you run `tala chat`. Details: [docs/setup.md](docs/setup.md).
`tala doctor` re-checks everything at any time.

Other commands:

| Command | Purpose |
| --- | --- |
| `tala setup [--default\|--recommended\|--advanced] [--check]` | First-run wizard: hardware-aware setup and model downloads |
| `tala ask "..."` | One question, then exit |
| `tala packs list [--all]` | Tools available here (and why others are not) |
| `tala packs show NAME` | Full definition of a tool |
| `tala packs validate [PATH...] [--strict]` | Lint packs (use in CI for your own packs) |
| `tala packs trust [DIR] [--revoke]` | Allow packs from `<DIR>/.tala/packs` (untrusted by default) |
| `tala facts add/list/remove` | Things the assistant should always remember ("my phone is 192.168.1.20") |
| `tala audit` | Recent tool executions |
| `tala eval retrieval [--embeddings]` / `tala eval agent` | Measure tool-selection quality on the golden set |

Inside `tala chat`: `/tools`, `/history`, `/reset`, `/exit`. Sessions are saved and resume automatically
(`tala chat --session work`).

## Add your own tool in two minutes

Create `~/.config/tala/packs/mine.yaml` (Windows: `%LOCALAPPDATA%\tala\packs\`;
run `tala doctor` to see the exact path), or `./.tala/packs/` for a per-project pack (project packs load only after `tala packs trust`,
because a pack defines what may run on your machine):

```yaml
pack: mine
tools:
  - name: git_branch_list
    description: List the local git branches of the current repository.
    risk: read_only
    examples: [which branches do I have, list my git branches]
    run:
      any: {exe: git, args: [branch, --list]}
```

```bash
tala packs validate      # catches mistakes before the model ever sees the tool
tala chat                # "which branches do I have?"
```

## Configuration

Optional `config.yaml` (location shown by `tala doctor`). Everything has a default; override only what
you need. Environment variables use `TALA__SECTION__KEY=value`.

```yaml
models:
  main:   {name: "gemma4:e4b", num_ctx: 8192}     # shared by chat, executor, summarizer
  router: {name: "granite4.1:3b", num_ctx: 2048}
agents:
  executor: {model: main, temperature: 0.1}
runtime:
  max_steps: 3                                    # tool rounds per request
  direct_output_chars: 600                        # fastest: show small results without a summary
safety:
  tool_overrides: {git_status: auto, docker_ps: ask}
packs:
  dirs: [~/team-packs]
  disabled_tools: [kill_process]
```

Full reference: [docs/configuration.md](docs/configuration.md). For response speed (time to first output,
fast path, warm-up) see [docs/performance.md](docs/performance.md).

## Project layout

```
src/assistant/
  domain/      pure models: ToolSpec, risk levels, events, errors
  packs/       YAML loading, lint, per-OS availability registry
  tools/       argument validation, argv rendering, bounded subprocess runner, LangChain tools
  retrieval/   hybrid BM25 + vector tool index with confidence tiers
  safety/      approval policy, audit log, output fencing
  llm/         model factory (Ollama; pluggable), health checks
  memory/      session checkpoints, history budgeting, long-term facts
  agent/       LangGraph: route -> executor -> authorize -> run -> summarize
  service.py   Assistant.send()/resume() -> typed events (the only front-end contract)
  bootstrap.py composition root
  cli/         thin Typer/rich front end
  builtin_packs/  95 tools (system, processes, network, files, git, docker, adb, npm, winget ...)
tests/         unit, pack quality gate, integration (scripted model), architecture
```

## Renaming or rebranding

The product name, command, environment-variable prefix and folder names live in one file:
[`src/assistant/domain/branding.py`](src/assistant/domain/branding.py). Change the constants there, rename
the console script and project name in `pyproject.toml`, and search-replace the Markdown docs. A test
(`tests/test_branding.py`) fails if the code base hard-codes any of these elsewhere.

## Development

```bash
pytest                      # 251 tests, fully offline (93% coverage)
ruff check . && ruff format --check .
mypy                        # strict
lint-imports                # layer contracts (also part of pytest)
tala eval retrieval -v       # tool-selection regression check
```

CI runs all of the above on Windows, Linux and macOS (`.github/workflows/ci.yml`).

## Status and limits (v3.0)

- Front end: CLI. The service API is front-end agnostic; an HTTP/WebSocket or tray adapter is the next step.
- Long-running/interactive programs (GUI apps, `scrcpy` mirroring) are not supported as tools yet.
- Commands are not OS-sandboxed; protection comes from approval policy, constraints and bounded execution.
- Small models (2-4B) make mistakes. Measure with `tala eval agent` before trusting a model, and keep
  mutating tools on `ask`.

See [CHANGELOG](CHANGELOG.md) and the decision records in [.10x/adrs](.10x/adrs). Maintainers: releasing
is described in [docs/publishing.md](docs/publishing.md).

## License

Copyright 2026 Achintha Bandara. Licensed under the [Apache License, Version 2.0](LICENSE): you may use,
modify and distribute it, including commercially, as long as you keep the copyright and [NOTICE](NOTICE)
files and state significant changes. It includes an explicit patent grant and comes with no warranty.
