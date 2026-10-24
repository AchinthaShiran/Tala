# DBA: v3-core

SQLite files (all under the data dir, WAL not needed: single process):
- `checkpoints.sqlite`: LangGraph SqliteSaver (owned by the library; schema not ours).
- `tool_index.sqlite`: `tools_meta(id PK AUTOINCREMENT, name UNIQUE, hash, embedded)`, FTS5 `tools_fts(name, description, keywords, category, examples; porter unicode61)` keyed by `tools_meta.id`, vec0 `tools_vec(embedding float[N] distance_metric=cosine)`, `index_meta(key,value)` for `embedding_id` and `dim`.
- `facts.sqlite`: `facts(key PK, value, updated)`.
Index is a pure cache: deleting it is safe (rebuilt on start). Rebuild triggers: tool text hash change (per tool), embedding model change (all vectors), dimension change (vec table recreated). No migrations needed; schema is created idempotently. Queries are parameterised; FTS input is tokenised to `[A-Za-z0-9]+` and quoted, so query text cannot inject FTS syntax (tested).
Scale: brute-force KNN over hundreds of tools is sub-millisecond; revisit at >10k tools.
