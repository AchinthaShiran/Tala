# ADR-004: One shared hybrid tool index with confidence tiers driving routing

**Status:** Accepted. **Date:** 2026-10-24. **Feature:** retrieval. **Author:** 10x-Team (Architect + DBA)

## Context
v2 had two indexers on one DB file; the router probed FTS with every word (no stop-words), so most chat went to the executor; `min_score` applied to RRF scores (range ~0.0125-0.033) never filtered; embedding dimension was hard-coded 768.

## Decision
- One `ToolIndex` (SQLite: FTS5 porter, sqlite-vec `vec0` cosine, `tools_meta` hash table, `index_meta` for model+dimension). Embeddings via a LangChain `Embeddings` object (prefix wrapper for nomic).
- Indexed text: name, description, keywords, category, examples. Re-embed only changed hashes; rebuild vec table when model/dimension changes.
- Search: stop-word-filtered tokens; per-token FTS for coverage; combined FTS for BM25 rank; cosine similarity; RRF for ordering.
- **Confidence:** candidates = lexical hits plus vector hits with `similarity >= min_similarity`. STRONG if top has `coverage >= 0.5` or `similarity >= strong_similarity`; WEAK if candidates exist otherwise; NONE if no candidates.
- Routing: STRONG → executor; NONE → chat (no LLM call); WEAK → one cheap router-LLM call.
- BM25-only mode when no embedder or the vector extension is unavailable.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
| --- | --- | --- | --- |
| LangChain vector store (Chroma/FAISS) | Standard | Extra deps, no FTS fusion | sqlite-vec already local and single-file |
| LLM-only router | Simple | Latency, VRAM for extra model | Retrieval already answers most cases |
| Raw RRF threshold | Simple | Not interpretable | Defect B8 |

## Consequences
Positive: honest "no tool" signal, fewer LLM calls, cross-OS fallback. Negative: thresholds need tuning (eval harness provides this). Risk: sqlite extension loading unsupported on some Pythons, so BM25 fallback covers it.
