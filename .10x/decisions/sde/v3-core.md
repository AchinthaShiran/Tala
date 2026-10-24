# SDE: v3-core: what was built

All planned layers shipped: domain, packs (loader/validator/registry), tools (arguments/rendering/runner/executor+LangChain adapter), safety (policy/audit/fencing), retrieval (hybrid index), llm (factory/health), memory (checkpointer/history/facts), agent (LangGraph), service, bootstrap, CLI, evaluation, 95 builtin tools, docs, CI.

## Deviations from the plan
- Added **project-pack trust** (`config.trust`, `deskaide packs trust`): found while self-reviewing; a cloned repo's `.deskaide/packs` could otherwise define tools with an arbitrary `risk`.
- Added `output_encoding` validation (unknown codec would crash execution).
- Retrieval confidence rule tightened after the first eval run (single generic word such as "today" matched a keyword and counted as STRONG): STRONG now needs a tool-name match or >=2 matched terms.
- Layer contract adjusted: `evaluation` sits above `service` (it drives the service), not below.
- `scrcpy_mirror*` tools dropped (long-running GUI processes cannot run under a timeout).
- Only `converted` v2 packs have derived examples (humanised name + description); curate them over time.

## Tech debt
- Converted pack examples are generic; golden set covers ~35 tools, not all 95.
- CLI `chat` loop is thin but untested against a real TTY (covered via CliRunner).
- Windows `list_directory` uses `tree` (recursive); a non-recursive listing needs script-tool support.
- No HTTP adapter yet (designed for, not built).
- `PendingCall` mode is rewritten in `authorize`; acceptable but could be a separate typed record.
