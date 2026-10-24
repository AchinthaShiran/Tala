# ADR-001: LangGraph agent loop with interrupt-based approval and SQLite checkpointer

**Status:** Accepted. **Date:** 2026-10-24. **Feature:** agent-core. **Author:** 10x-Team (Architect + Staff Engineer)

## Context
v2 hand-rolled the loop in the CLI (`while True`), supported one tool call, and could not be reused by another front end. Approval, execution and summarising lived in `__main__.py`.

## Decision
Model the agent as a LangGraph `StateGraph`: `route → (chat | executor) → authorize → run_tools → (executor | summarizer)`. `authorize` calls `langgraph.types.interrupt()` with approval requests; any front end resumes with `Command(resume=decisions)`. State is checkpointed with `SqliteSaver` keyed by `thread_id = session_id`. A `Assistant` service wraps the graph and exposes typed events.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
| --- | --- | --- | --- |
| `create_agent` prebuilt | Least code | No routing tier, no custom policy gate, hard to test | Safety gate must be explicit |
| Custom loop in service | Full control | Re-implements persistence, streaming, resumption | LangGraph gives these for free |
| CLI-owned loop (v2) | Simple | Not reusable, untestable | The defect we are fixing |

## Consequences
Positive: resumable sessions, front-end-agnostic approval, bounded multi-step loops, testable nodes.
Negative: LangGraph API churn risk; interrupts re-run the node on resume (nodes before `interrupt` must be pure).
Risks: version drift, so pin a tested range in `pyproject.toml` and cover the flow with integration tests.

## Dependencies
Constrains ADR-003 (policy executes inside `authorize`) and ADR-005 (event API mirrors graph updates).
