# ADR-005: Strict layering and a typed event API as the only front-end contract

**Status:** Accepted. **Date:** 2026-10-24. **Feature:** architecture. **Author:** 10x-Team (Architect + Staff Engineer)

## Context
v2 mixed UI, approval and execution in the CLI; the SDK contracts were partly unused; there were three packages for ~1500 lines.

## Decision
- A single installable package `assistant` with sub-packages: `domain` (pure models, enums, events, errors), `packs`, `tools`, `retrieval`, `safety`, `llm`, `memory`, `agent`, `config`, `evaluation`, plus `service.py`, `bootstrap.py` (composition root) and `cli/`.
- Dependency rule (import-linter): `domain` imports nothing internal; `packs` and `tools` depend on `domain` only (`tools` may use `packs` types); `retrieval`, `safety`, `llm`, `memory` do not import `agent`/`service`/`cli`; `agent` does not import `cli`; only `bootstrap` wires concrete classes.
- Front ends consume `Assistant.send()/resume()` -> `Iterator[Event]` (pydantic discriminated union). A future HTTP/WebSocket adapter serialises the same events.
- Ports as `Protocol`s where substitution matters: `CommandRunner`, `AuditLog`, `ToolCatalog`.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
| --- | --- | --- | --- |
| Multi-package workspace (v2) | Hard boundaries | Packaging overhead, cross-package churn | Layer rules via import-linter give the same guarantee |
| CLI-first, extract later | Fast | Repeats v2's problem | Core must be UI-agnostic from day one |

## Consequences
Positive: one wheel, enforceable boundaries, easy second front end. Negative: boundary discipline relies on the lint contract. Risk: contract rot, so it runs in CI and in the test suite.
