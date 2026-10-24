# Configuration reference

Layers, lowest to highest priority: built-in defaults < `config.yaml` < environment variables <
programmatic overrides. Unknown keys are errors (typos are caught). `tala doctor` prints the config path.

Environment variables: `TALA__<SECTION>__<KEY>=<yaml value>`, for example
`TALA__MODELS__MAIN__NAME=gemma4:e4b`, `TALA__RUNTIME__MAX_STEPS=5`.
`TALA_HOME=/some/dir` relocates config and data (useful for portable installs and tests).

```yaml
models:                         # named models; agents refer to these names
  router:
    provider: ollama            # ollama (default); others via llm.register_provider
    name: "granite4.1:3b"
    num_ctx: 2048               # context window requested from the server
    keep_alive: "30m"
    base_url: "http://localhost:11434"
    request_timeout: 120
  main:
    name: "gemma4:e2b"
    num_ctx: 8192

embeddings:                     # null disables vectors (keyword-only retrieval)
  provider: ollama
  name: nomic-embed-text

agents:                         # router, chat, executor, summarizer (all required)
  executor:
    model: main                 # key from `models`
    temperature: 0.1
    max_tokens: 512
    think: false                # explicit false keeps thinking-capable models from reasoning
    prompt: null                # replace the built-in system prompt

retrieval:
  top_k: 4                      # tools offered to the executor (fewer = faster prompt)
  min_similarity: 0.55          # cosine floor for a vector candidate
  strong_similarity: 0.70       # cosine at which a vector hit is a confident match alone
  corroborated_similarity: 0.60 # cosine at which ONE keyword match plus similarity counts as confident
  min_coverage: 0.5             # share of query terms a multi-term keyword match must cover
  use_embeddings: true

safety:
  modes: {read_only: auto, mutating: ask, destructive: confirm}
  tool_overrides: {}            # tool name -> auto|ask|confirm|deny
  pack_overrides: {}            # pack name -> auto|ask|confirm|deny
  allow_auto_mutating: false    # required to set mutating tools to auto
  audit_log: true

runtime:
  max_steps: 3                  # tool rounds per request
  followups: auto               # auto | always | never: extra executor rounds after the first results
  direct_output_chars: 0        # >0: show one small successful read-only result verbatim (no summary)
  fast_path: true               # skip the executor model for decisive, argument-free read-only tools
  fast_path_margin: 0.05        # similarity lead the top tool needs over the runner-up
  max_repairs: 2                # attempts to fix an invalid tool call
  history_budget_ratio: 0.6     # share of num_ctx given to conversation history
  tool_output_chars: 6000       # per-output cap before it reaches the model
  recent_turns_full_tools: 1    # older turns keep only a short digest of tool output

packs:
  dirs: []                      # extra pack directories (highest priority)
  disabled_packs: []
  disabled_tools: []

data_dir: null                  # override where sessions, index, facts and audit log live
```

## Model guidance

- Give every agent that shares a model the same `num_ctx` (a different value forces a reload).
- The executor needs a model with tool calling (`tala doctor` checks the capability flag).
  Models under ~4B parameters make more argument mistakes; measure with `tala eval agent`.
- Tune `retrieval.*` with `tala eval retrieval --embeddings -v` rather than by feel.

## Files

| File | Location (`<config>` / `<data>` from `tala doctor`) |
| --- | --- |
| Config | `<config>/config.yaml` |
| User packs | `<config>/packs/` |
| Sessions (checkpoints) | `<data>/checkpoints.sqlite` |
| Tool index | `<data>/tool_index.sqlite` (safe to delete; rebuilt) |
| Facts | `<data>/facts.sqlite` |
| Audit log | `<data>/audit.jsonl` |
