# SRE: v3-core (a desktop app: "ops" means supportability)

SLO-style targets (local, single user): startup to prompt < 3 s with warm models; keyword-only routing decision < 50 ms; any single tool execution bounded by its timeout (default 30 s); no command able to hang the process (timeout + tree kill, stdin closed).
Observability: stdlib logging under `assistant.*` (warnings for degraded retrieval, router failures, unreadable trust file); JSONL audit log of every tool execution/denial; `deskaide doctor` (platform, config path, packs, tool availability, Ollama reachability, models pulled, tool-calling capability, untrusted project packs).
Runbook:
| Symptom | Check | Fix |
| --- | --- | --- |
| "I can't reach the language model" | `deskaide doctor` | start Ollama / fix `models.*.base_url` |
| "model ... not installed" | `deskaide doctor` | `ollama pull <name>` |
| Tool never offered | `deskaide packs list --all` | install the executable, or add a variant for this OS |
| Wrong tool chosen | `deskaide eval retrieval -v` | add `examples`/`keywords`, add a golden case, tune `retrieval.*` |
| Pack ignored | `deskaide packs validate` | fix reported file/tool; for project packs `deskaide packs trust` |
| Slow answers | `ollama ps` shows CPU-only? | use a smaller model, lower `num_ctx`, or GPU |
| Corrupt/odd index | delete `tool_index.sqlite` | rebuilt on next start |
| Need to see what ran | `deskaide audit -n 50` | |
Known operational limit: CPU-only inference is slow (live agent eval averaged ~60 s per request on the reference machine with a 4.6B model).
