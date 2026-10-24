# From the v2 prototype: how each review finding was addressed

Source: `desktop_assistant_v2/docs/review-and-improvements.md`.

| # | v2 problem | v3 resolution | Proof |
| --- | --- | --- | --- |
| B1 | No pack set `risk_level`; mutating tools auto-ran | `risk` is mandatory in `ToolSpec`; every builtin tool classified; policy engine | `test_builtin_packs::test_risk_distribution_is_sane`, `test_safety` |
| B2 | Argument injection (`--force`) | Leading-dash guard, enum/pattern/length constraints, strict types | `test_arguments_and_rendering` |
| B3 | Optional parameters crashed the tool | Defaults applied; `when:` conditional args; loader enforces correct use | `test_domain_tool`, `test_arguments_and_rendering` |
| B4 | Declared-but-unused parameters (`adb_tcpip`) | Loader error: every parameter must be used | `test_domain_tool::test_unused_parameter_rejected` |
| B5 | Tool without executable (`get_system_info`) | Structural invariant; replaced by `os_info` etc. | `test_builtin_packs` |
| B6 | `.cmd` shims (`npm`, `winget`) not found | `shutil.which` resolution, full path executed | `tools.executor.prepare`, `packs.registry` |
| B7 | Router sent almost everything to the executor | Stop-words, confidence tiers, name/term-coverage rules; chit-chat bypasses tools | `test_retrieval`, eval: false-strong 0% with embeddings |
| B8 | `min_score` was a no-op | Thresholds on cosine similarity and lexical coverage, tuned by eval | `tala eval retrieval` |
| B9 | Tool-call messages sent to Ollama in the wrong shape | LangChain `ChatOllama` handles the wire format natively | live smoke test, agent flow tests |
| B10 | Executor could call tools it was not offered | Validation against the offered set | `test_tool_not_offered_is_rejected` |
| B11 | All call ids were `call_0` | Unique ids guaranteed per message | `agent.nodes._with_unique_ids` |
| B12 | Windows code-page garbling | UTF-8 with `errors=replace`; per-tool `output_encoding` incl. `oem`; CLI forces UTF-8 output | `test_runner` |
| B13 | Output truncation only in the CLI | Bounded capture in the runner + fenced truncation before prompting | `test_runner::test_output_is_bounded...` |
| B14 | Unbounded history vs `num_ctx` | Token-budgeted history, old tool output compacted | `test_memory_and_config` |
| B15 | Memory loaded then wiped on exit | LangGraph SQLite checkpointer; explicit `/reset`; long-term facts | `test_agent_flow::test_sessions_persist_and_reset` |
| B16 | Pack failures only printed | `PackIssue`s with file and tool; `packs validate`; duplicates are errors | `test_packs` |
| B17 | Prefix path check in gateway | Gateway dropped (it was unused); no file I/O API without a caller | n/a |
| B18 | No HTTP timeouts; embedding latency each search | `request_timeout`; embedding failure cool-down; friendly Ollama-down message | `test_retrieval`, `service.friendly_error` |
| B19 | Dead code (`max_steps`, protocols, `AgentContext`) | Removed; `max_steps` is now real | n/a |
| B20 | Convoluted approval logic in the CLI | `PolicyEngine.decide` + graph `interrupt`; CLI only renders | `test_agent_flow` |
| 3.1 | Loop lived in the CLI | `Assistant` service + typed events + LangGraph | `service.py` |
| 3.2 | Single tool call | Bounded multi-step loop, parallel read-only calls | `test_multi_step_loop_runs_second_tool` |
| 3.3 | "OS agnostic" in name only | Logical tools, per-OS variants, availability gating, layered packs | `test_every_os_has_core_capabilities` |
| 3.4 | Thin packs | Examples, keywords, constraints, timeouts, lint; 95 tools | `test_builtin_packs` |
| 3.5 | Coarse safety | Policy, exact command, fencing, post-output tightening, audit | `test_safety`, `test_agent_flow` |
| 3.8 | Hard-coded embedding dimension | Dimension/model change detected, index rebuilt | `test_retrieval::test_changed_embedding_model_or_dimension...` |
| 5 | Minimal tests, no eval | 251 tests; golden set; retrieval and agent evals; architecture test; CI matrix | `tests/`, `tala eval` |

New problems found and fixed while building v3: `adb shell` commands were open to **remote-shell injection**
through unconstrained package/path parameters (now pattern-constrained and tested); v2 `enum` parameters
had no allowed values; Rich markup swallowed `[math]` in displayed PowerShell commands; legacy Windows
code pages crashed on status glyphs.

Intentionally left out: `scrcpy_mirror*` (long-running GUI), the unused file gateway.
