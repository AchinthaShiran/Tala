# Architect: v3-core
See ADR-001..005 and docs/architecture.md. Layers: domain <- packs/tools <- retrieval/safety/llm/memory <- agent <- service/bootstrap <- cli.
Failure modes: Ollama down (doctor + friendly error), embeddings down (BM25 fallback), tool missing (unavailable, not offered), model emits bad args (validate + repair), runaway output (head+tail cap), runaway loop (max_steps), hung process (timeout + tree kill).
