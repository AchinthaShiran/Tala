# ADR-002: Pack format: logical tools with per-OS variants, strict lint, layered roots

**Status:** Accepted. **Date:** 2026-10-24. **Feature:** packs. **Author:** 10x-Team

## Context
v2 packs were thin Windows wrappers: no risk tags, optional arguments crashed, unreferenced parameters were silently ignored, duplicate names silently overrode, tools whose executable was missing were still offered to the LLM.

## Decision
- One YAML file holds `pack`, `version`, `description`, `tools[]`.
- A tool is a *logical capability* (`ping_host`) with `run: {windows|linux|macos|any: {exe, args}}`. The LLM sees one schema on every OS.
- `risk` is required (`read_only|mutating|destructive`); destructive requires `confirm_message`.
- `parameters` are typed with constraints (`enum`, `pattern`, `minimum`, `maximum`, `max_length`, `default`, `optional`, `allow_dash`).
- `args` items are strings with `{param}` placeholders or conditionals `{when: param, args: [...]}`; a value gates a flag only when present/truthy.
- Layered roots: builtin < user config dir < project `.assistant/packs`; later overrides earlier and the override is reported.
- Validator rules: unknown/unused placeholders, unreferenced params, optional-without-default used unconditionally, duplicate names within a root, invalid constraints, missing risk, <1 example.
- Availability: platform variant exists and `shutil.which(exe)` resolves, otherwise the tool is `unavailable` with a reason and is never offered.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
| --- | --- | --- | --- |
| Keep v2 flat format + add `platforms` | Small change | Per-OS argv still duplicated as separate tool names | LLM sees OS-specific names |
| Python plugin classes | Powerful | Contributors need code; harder to sandbox | Violates "YAML only" goal |
| Pack-level platform gate only | Simple | Cannot express `ping -n` vs `-c` | Too coarse |

## Consequences
Positive: one stable schema per capability, safe contributions via `pack validate`, honest availability. Negative: authors write more per-OS YAML. Risk: format growth; mitigate with `version` field on packs and a schema version later.
