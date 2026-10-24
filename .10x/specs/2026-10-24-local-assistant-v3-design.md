# Local Assistant v3: Design Spec

Date: 2026-10-24. Status: approved by user. Supersedes the v2 prototype (see `desktop_assistant_v2/docs/review-and-improvements.md`).

## Goal
A local, OS-agnostic desktop AI assistant. The user chats in natural language; a local LLM (Ollama) selects and runs *tools* defined in YAML **packs**. New capabilities are added by dropping a YAML file in a pack directory, with no Python required.

## Decisions taken with the user
| Topic | Decision |
| --- | --- |
| Agent stack | LangChain (`langchain-core`, `langchain-ollama`) + LangGraph with SQLite checkpointer |
| v3.0 front end | Core service with a typed event API + rich CLI. An HTTP adapter is a later, additive adapter. |
| OS support | Logical tools with per-OS command variants, platform gating, executable gating, layered packs |
| Process | 10x-team: spec, ADRs, state files, then code and tests |
| Defaults | package `assistant`, command `lpa`, models `granite4.1:3b` (router) and `gemma4:e2b` (rest), configurable |

## Non-goals (v3.0)
GUI/tray, voice, cloud LLM providers (interface ready), script/HTTP/MCP tool types (extension point designed, not built), multi-user.

## Requirements
R1. Packs: YAML, one logical tool with `run` variants per `windows|linux|macos|any`; mandatory `risk`; parameter constraints; conditional args; defaults; examples/keywords for retrieval.
R2. Pack loading: layered roots (builtin < user < project), later overrides earlier; every problem reported with file and tool; strict validator (`lpa packs validate`).
R3. Availability: a tool is offered to the LLM only when it has a variant for the current OS and its executable resolves with `shutil.which`.
R4. Execution: never `shell=True`; argv rendering from validated args; leading-dash guard; per-tool timeout; process-tree kill; bounded output (head+tail); UTF-8 decoding with per-tool override.
R5. Retrieval: one shared index, BM25 + vector with RRF, confidence tiers (STRONG/WEAK/NONE) used for routing; BM25-only graceful fallback; embedding-dimension safety.
R6. Agent: route, then a bounded plan/authorize/run/observe loop (`max_steps`), then summarize. Validation against the *offered* tools, repair loop, real call ids, parallel read-only calls.
R7. Safety: policy engine (auto/ask/confirm/deny) by risk, with per-tool/pack overrides that cannot silently auto-run destructive tools; exact command line shown on approval; approval is a graph `interrupt`; untrusted-output fencing and a stricter policy after tool output; JSONL audit log.
R8. Memory: SQLite checkpointer per session (resumable), history token budget and tool-output compaction, long-term fact store injected into the prompt.
R9. Service API: `Assistant.send()/resume()` yields typed events; the CLI contains no business logic.
R10. Ops: `lpa doctor` (Ollama reachable, models pulled, embedding dim), layered config (defaults < file < env < flags), platformdirs paths.
R11. Quality: unit + pack-lint + integration (scripted model) + architecture tests; golden eval set and runner; CI on Windows/Linux/macOS; ruff + mypy strict.

## Architecture
Layers (imports flow downward only; enforced by import-linter):
```
cli  ─►  service/bootstrap  ─►  agent, retrieval, safety, memory, llm  ─►  tools, packs  ─►  domain
```
See `docs/architecture.md` and ADR-001..005.

## Acceptance
- `pytest` green on Windows; `lpa packs validate` reports zero errors on builtin packs.
- Retrieval eval recall@6 >= 0.85 on the golden set (BM25 mode).
- End-to-end smoke against local Ollama answers "how much disk space is free" using `disk_free`.
- Mutating/destructive tools cannot run without approval in default config (tested).
