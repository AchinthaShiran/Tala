# Safety model

The assistant turns model output into commands on a real machine, so safety is a feature with tests,
not a prompt. Decision record: [ADR-003](../.10x/adrs/003-safety-model.md).

## Threats and mitigations

| Threat | Mitigation | Where |
| --- | --- | --- |
| Model proposes a harmful action | Mandatory per-tool `risk`; policy requires approval for mutating/destructive; destructive needs the tool name typed | `safety.policy`, `agent.nodes.authorize` |
| Model hides what it will do | Approval shows the **exact resolved command line**, the same `argv` that is then executed | `tools.executor.prepare` |
| Option injection (`--force`, `-rf`) | Strings may not start with `-` unless the pack opts in | `tools.arguments` |
| Shell injection | No shell anywhere; argv list only; `shell=False` is asserted by tests | `tools.runner` |
| Second-order shell (`adb shell`, `cmd /c`) | Pack authors constrain values; builtin tests prove the patterns reject `;` and `$()` | `docs/pack-authoring.md`, `tests/test_builtin_packs.py` |
| Prompt injection via tool output (file names, logs, git messages) | Output wrapped as untrusted data, forged delimiters neutralised, instructions to ignore commands inside it; **after any tool output, mutating/destructive calls need approval even if configured as auto** | `safety.fencing`, `PolicyEngine` |
| Model calls an unoffered or unknown tool | Calls validated against the tools offered this turn | `agent.nodes._validate_calls` |
| Runaway loops | `max_steps`, `max_repairs`, graph recursion limit | `agent`, `service` |
| Hung or fork-bombing command | Per-tool timeout, whole process tree killed | `tools.runner` |
| Memory exhaustion from huge output | Bounded capture (head + tail) in constant memory, again bounded before prompting | `tools.runner`, `safety.fencing` |
| Interactive prompts hanging the agent | stdin closed | `tools.runner` |
| Config weakening safety by accident | Settings reject `destructive: auto`; `mutating: auto` needs `allow_auto_mutating: true` | `config.settings` |
| No record of what ran | Append-only JSONL audit of tool, argv, approver, status, exit code, duration | `safety.audit`, `tala audit` |
| Malicious pack in a cloned repository | Project packs are **not loaded until the directory is trusted** (`tala packs trust`, stored outside the repo); `tala doctor` warns when ignoring them | `config.trust`, `bootstrap.pack_roots` |
| Pack mistakes | Loader reports per tool; strict validator; builtin packs are a CI gate | `packs`, `tests/test_builtin_packs.py` |

## Approval modes

| Mode | Meaning |
| --- | --- |
| `auto` | Runs without asking |
| `ask` | Yes/no prompt |
| `confirm` | User must type the tool name |
| `deny` | Never runs |

Defaults: `read_only=auto`, `mutating=ask`, `destructive=confirm`. Overrides: `safety.tool_overrides` (tool
name) beat `safety.pack_overrides` (pack name) beat the risk default. A new message while an approval is
open counts as "no".

## Residual risks (v3.0)

- **No OS sandbox.** Approved commands run with the user's privileges. Never run the assistant elevated.
- **Approved is approved.** A user who confirms a harmful command gets that command. The prompt shows
  the full command line and, for destructive tools, a pack-written warning.
- **Read-only tools can still leak data into the model context** (for example `adb_logcat_recent`). That is
  local, but remember it when choosing a non-local provider.
- **Secrets in arguments** appear in the audit log. Do not pass secrets as tool arguments.
- **Small local models are unreliable.** The safety layers assume the model is wrong or manipulated.

## Reviewing a pack for safety

1. Is `risk` the highest level the command can reach with any allowed argument?
2. Is every string parameter constrained (`pattern`/`enum`)?
3. Does the command re-parse arguments (`shell`, `-Command`, `cmd /c`, `sh -c`)? If yes, tighten the alphabet.
4. Could output contain attacker-controlled text (file names, web pages, commit messages)? Fine, it is
   fenced, but do not mark follow-up tools `auto`.
5. Does it need elevation? Do not offer it.
