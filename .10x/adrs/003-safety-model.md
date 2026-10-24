# ADR-003: Safety model: policy engine, untrusted-output fencing, bounded execution, audit

**Status:** Accepted. **Date:** 2026-10-24. **Feature:** safety. **Author:** 10x-Team (Architect + Security)

## Context
The assistant runs commands on a real PC from LLM output. v2 defaulted all tools to read-only, so nothing prompted; arguments could become flags; tool output was fed back to the LLM unmarked.

## Decision
1. **Risk is mandatory per tool**; unknown risk is rejected at load.
2. **Policy engine** maps risk to a mode: `read_only=auto`, `mutating=ask`, `destructive=confirm` (typed tool name). Per-tool/per-pack overrides may tighten or relax *within limits*: destructive can never be `auto`; mutating can be `auto` only with explicit `safety.allow_auto_mutating: true`.
3. **Post-output tightening:** once any tool output entered the context in a run, mutating/destructive calls are at least `ask` regardless of overrides (prompt-injection mitigation).
4. **Argument defence:** schema constraints, strict types, leading-dash guard, `--` is the pack author's choice via args.
5. **Exact command line** (resolved argv) is shown on every approval.
6. **Bounded execution:** per-tool timeout, process-tree kill, head+tail output cap, no shell.
7. **Fencing:** tool output is wrapped in `<tool_output ...>` with an untrusted-data instruction; embedded fence markers are neutralised.
8. **Audit:** append-only JSONL (timestamp, session, tool, argv, decision, approver, exit code, duration, truncated).

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
| --- | --- | --- | --- |
| Single `auto_execute` flag (v2) | Simple | Too coarse; promotes everything | The defect |
| Allow-list of commands only | Strong | No flexibility for packs | Packs already are the allow-list |
| OS sandbox (AppContainer/seccomp) | Real isolation | Per-OS heavy work | Future ADR |

## Consequences
Positive: safe-by-default, auditable. Negative: more prompts. Risks: LLM can still request harmful but approved actions, mitigated by exact-command display and typed confirmation. Residual: no OS sandbox in v3.0.
