# Architecture

Decisions are recorded as ADRs in [`.10x/adrs`](../.10x/adrs); this page describes the result.

## Layers

Imports flow downward only. `tests/test_architecture.py` runs [import-linter](https://import-linter.readthedocs.io)
against the contract in `pyproject.toml`, so a violation fails the build.

```
cli                         presentation only (typer, rich)
bootstrap | evaluation      composition root | golden-set evaluation
service                     Assistant.send()/resume() -> typed events
agent                       LangGraph nodes and graph
retrieval | safety | llm | memory
tools                       argument validation, rendering, runner, LangChain adapter
packs                       YAML loading, lint, availability
config                      settings, paths
domain                      pure models (no I/O, no framework imports)
```

## Request lifecycle

```
                       ┌─────────┐   NONE / chit-chat
 user text ──► route ──┤ search  ├──────────────────────────► chat ───────────────► END
                       │ index   │   WEAK ─► router LLM ─┐
                       └────┬────┘                       │ "chat"
                       STRONG│ or "act"                  ▼
                            ▼                          chat
   ┌──────────────────► executor (LLM + bound tools)
   │                        │ tool calls?
   │         none (step 0) ─┴─► chat          none (after a tool) ─► summarizer ─► END
   │                        │
   │                 validate against OFFERED tools + JSON constraints
   │           invalid ─► feedback ToolMessage ─► executor (max_repairs)
   │                        ▼
   │                   authorize ── policy ──► auto / ask / confirm / deny
   │                        │            └─ ask/confirm: interrupt() ► front end ► resume
   │                        ▼
   │                   run_tools (parallel if all read-only), fenced output, audit
   └─ more steps left ◄─────┤
                            └─ max_steps reached or something denied ─► summarizer ─► END
```

Key properties:

- **One retrieval index** shared by routing and the executor. Routing uses confidence tiers, so
  most chit-chat never calls a model for routing and most tool requests skip the router model entirely.
- **The executor only sees 4-8 tools** (top-k from the index) and its calls are validated against that
  offered set, not against every tool.
- **Approval is a graph `interrupt`.** The graph state is checkpointed (SQLite), so a front end can show the
  request, wait any amount of time, and resume. A new user message while waiting counts as a denial.
- **State is per turn:** `route` resets step/repair/denial counters, so nothing leaks between turns.
- **History is budgeted:** old tool outputs are compacted, oldest whole turns are dropped to fit
  `num_ctx`, and the latest turn is always kept.

## Components

| Module | Responsibility | Notable decisions |
| --- | --- | --- |
| `domain.tool.ToolSpec` | A logical tool with per-OS `run` variants | Invariants enforced at construction: placeholders declared and used, optional params conditional, destructive needs a confirm message, risk mandatory |
| `packs.loader` | Layered loading (builtin < user < project < extra dirs) | Never raises on content; every problem is a `PackIssue` with file and tool; overrides are reported |
| `packs.registry` | Availability per platform | `shutil.which` gating; unavailable tools keep a human-readable reason |
| `tools.arguments` | Coercion + constraints | Leading-dash guard, enum/pattern/range/length, unknown keys rejected, all errors reported together |
| `tools.runner` | Subprocess execution | No shell, stdin closed, timeout + process-tree kill, head+tail output cap in constant memory, `oem` code-page support |
| `tools.executor` | `prepare()` (validate + resolve exe + render) and `execute()` | The same `prepare` result is shown at approval and executed |
| `retrieval.index` | SQLite FTS5 + sqlite-vec, RRF | Confidence tiers; re-embeds only changed tools; rebuilds on model/dimension change; keyword fallback; vector retry cool-down |
| `safety.policy` | Risk to approval mode | Destructive never auto; mutating auto only with explicit opt-in; tightened after tool output |
| `safety.fencing` | Untrusted-output wrapper | Forged delimiters neutralised, head+tail truncation |
| `safety.audit` | JSONL trail | Thread-safe append, resolved argv, approver, exit code, duration |
| `llm.factory` | Chat/embedding models | Provider registry (`register_provider`); explicit `reasoning=False`; nomic prefixes |
| `memory` | Checkpointer, history budget, facts | Sessions resumable; facts injected into every prompt |
| `agent.nodes` | Graph nodes | Each node is a small method over `AgentDeps`; no globals |
| `service.Assistant` | Front-end contract | Streams `TokenEvent`, `ToolProposedEvent`, `ApprovalRequestedEvent`, `ToolResultEvent`, `FinalEvent`, `ErrorEvent` |
| `bootstrap` | Wiring | Every collaborator replaceable, which is how tests run offline |

## Extension points

| To add... | Do this |
| --- | --- |
| A capability | A YAML pack (no code) |
| An LLM provider | `llm.register_provider("name", chat_builder, embeddings_builder)` and `provider: name` in config |
| A front end | Consume `Assistant.send()/resume()` events (see `cli/render.py`); an HTTP adapter serialises the same pydantic events |
| A tool type beyond subprocess (script, HTTP, MCP) | Add a variant kind in `domain.tool` and a runner in `tools`; the policy, audit and approval flow stay unchanged |
| A safety rule | `safety.policy.PolicyEngine.decide` (covered by invariant tests) |
| Long-lived memory beyond facts | `memory/` behind the same prompt-injection point in `agent.nodes._system` |

## Failure modes

| Failure | Behaviour |
| --- | --- |
| Ollama down | `ErrorEvent` with an actionable message; `lpa doctor` explains |
| Embeddings down | Index logs once and uses keyword search; retried after a cool-down |
| `sqlite-vec` unsupported | Keyword-only mode |
| Tool executable missing | Tool is unavailable (never offered) with a reason in `lpa packs list --all` |
| Model emits invalid args | Error fed back as a `ToolMessage`, up to `max_repairs`, then a clear failure message |
| Model calls a tool it was not offered | Rejected, same repair loop |
| Command hangs | Killed with its children after the tool's timeout; model sees a timeout observation |
| Huge output | Head and tail kept at capture time and again before prompting |
| Pack file broken | Reported with file and tool name; other tools still load |
| Crash while waiting for approval | Checkpoint persists; `pending_approval()` shows it after restart |
