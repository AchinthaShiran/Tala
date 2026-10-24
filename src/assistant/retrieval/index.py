"""ToolIndex: shared hybrid (BM25 + vector) tool retrieval with confidence tiers.

See ADR-004. One SQLite file holds an FTS5 table, an optional sqlite-vec table and bookkeeping
tables. Without an embedder (or without extension support) it degrades to keyword search.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
import time
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from langchain_core.embeddings import Embeddings

from assistant.config import RetrievalSettings
from assistant.domain import ToolSpec
from assistant.retrieval.text import content_tokens

log = logging.getLogger(__name__)

_RRF_K = 60
_CANDIDATES = 30
_VECTOR_RETRY_SECONDS = 30.0


class Confidence(StrEnum):
    STRONG = "strong"  # a tool clearly matches
    WEAK = "weak"  # something matches, but ambiguously
    NONE = "none"  # nothing matches


@dataclass(frozen=True, slots=True)
class Hit:
    name: str
    score: float  # reciprocal-rank-fusion score, for ordering only
    coverage: float  # share of query terms found lexically
    similarity: float | None  # cosine similarity, when vectors are available
    matched_terms: int = 0  # query terms found lexically
    name_match: bool = False  # a query term appears in the tool's name


@dataclass(frozen=True, slots=True)
class SearchResult:
    hits: tuple[Hit, ...]
    confidence: Confidence

    @property
    def names(self) -> list[str]:
        return [h.name for h in self.hits]


class ToolIndex:
    def __init__(
        self,
        db_path: Path | str,
        settings: RetrievalSettings,
        embeddings: Embeddings | None = None,
        embedding_id: str = "",
    ) -> None:
        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings = settings
        self._embeddings = embeddings if settings.use_embeddings else None
        self._embedding_id = embedding_id
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._vec_supported = self._load_vec_extension()
        self._vectors_ready = False
        self._vector_retry_at = 0.0
        self._ids: dict[str, int] = {}
        self._names: dict[int, str] = {}
        self._create_schema()

    # -- lifecycle ---------------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def vectors_enabled(self) -> bool:
        return self._vectors_ready

    def _load_vec_extension(self) -> bool:
        try:
            import sqlite_vec

            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
        except (ImportError, AttributeError, sqlite3.Error) as exc:
            log.warning("sqlite-vec unavailable, using keyword search only: %s", exc)
            return False
        return True

    def _create_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS tools_meta ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, "
                "hash TEXT NOT NULL, embedded INTEGER NOT NULL DEFAULT 0)"
            )
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS tools_fts USING fts5("
                "name, description, keywords, category, examples, tokenize='porter unicode61')"
            )

    # -- indexing ----------------------------------------------------------------------------

    def sync(self, tools: Iterable[ToolSpec]) -> None:
        """Make the index reflect ``tools``: add/refresh changed ones, drop removed ones."""
        specs = {t.name: t for t in tools}
        with self._lock:
            existing = {
                name: (id_, digest, bool(embedded))
                for id_, name, digest, embedded in self._conn.execute(
                    "SELECT id, name, hash, embedded FROM tools_meta"
                )
            }
            self._reset_vectors_if_model_changed()
            with self._conn:
                for name, (id_, _, _) in existing.items():
                    if name not in specs:
                        self._delete_tool(id_, name)
                for name, spec in specs.items():
                    digest = hashlib.sha256(spec.retrieval_text().encode()).hexdigest()
                    known = existing.get(name)
                    if known is None or known[1] != digest:
                        self._upsert_tool(spec, digest, known[0] if known else None)
            self._refresh_maps()
            self._embed_pending()

    def _reset_vectors_if_model_changed(self) -> None:
        row = self._conn.execute("SELECT value FROM index_meta WHERE key='embedding_id'").fetchone()
        if row is not None and row[0] == self._embedding_id:
            return
        with self._conn:
            self._conn.execute("DROP TABLE IF EXISTS tools_vec")
            self._conn.execute("UPDATE tools_meta SET embedded = 0")
            self._conn.execute("DELETE FROM index_meta WHERE key IN ('dim', 'embedding_id')")
            self._conn.execute(
                "INSERT OR REPLACE INTO index_meta(key, value) VALUES ('embedding_id', ?)",
                (self._embedding_id,),
            )

    def _delete_tool(self, id_: int, name: str) -> None:
        self._conn.execute("DELETE FROM tools_fts WHERE rowid = ?", (id_,))
        if self._table_exists("tools_vec"):
            self._conn.execute("DELETE FROM tools_vec WHERE rowid = ?", (id_,))
        self._conn.execute("DELETE FROM tools_meta WHERE name = ?", (name,))

    def _upsert_tool(self, spec: ToolSpec, digest: str, id_: int | None) -> None:
        if id_ is None:
            cursor = self._conn.execute(
                "INSERT INTO tools_meta(name, hash, embedded) VALUES (?, ?, 0)", (spec.name, digest)
            )
            id_ = int(cursor.lastrowid or 0)
        else:
            self._conn.execute(
                "UPDATE tools_meta SET hash = ?, embedded = 0 WHERE id = ?", (digest, id_)
            )
            self._conn.execute("DELETE FROM tools_fts WHERE rowid = ?", (id_,))
            if self._table_exists("tools_vec"):
                self._conn.execute("DELETE FROM tools_vec WHERE rowid = ?", (id_,))
        self._conn.execute(
            "INSERT INTO tools_fts(rowid, name, description, keywords, category, examples) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                id_,
                spec.name.replace("_", " "),
                spec.description,
                " ".join(spec.keywords),
                spec.category or "",
                " ".join(spec.examples),
            ),
        )

    def _refresh_maps(self) -> None:
        rows = self._conn.execute("SELECT id, name FROM tools_meta").fetchall()
        self._ids = {name: id_ for id_, name in rows}
        self._names = {id_: name for id_, name in rows}

    def _embed_pending(self) -> None:
        if not (self._vec_supported and self._embeddings):
            self._vectors_ready = False
            return
        pending = self._conn.execute(
            "SELECT id, name FROM tools_meta WHERE embedded = 0 ORDER BY id"
        ).fetchall()
        if pending:
            texts = {name: self._retrieval_text_for(name) for _, name in pending}
            try:
                vectors = self._embeddings.embed_documents([texts[name] for _, name in pending])
            except Exception as exc:
                log.warning("embedding failed, using keyword search only: %s", exc)
                self._vectors_ready = False
                return
            if len(vectors) != len(pending) or not vectors or not vectors[0]:
                log.warning("embedding backend returned no vectors; using keyword search only")
                self._vectors_ready = False
                return
            self._store_vectors([id_ for id_, _ in pending], vectors)
        self._vectors_ready = self._table_exists("tools_vec")

    def _retrieval_text_for(self, name: str) -> str:
        row = self._conn.execute(
            "SELECT name, description, keywords, category, examples FROM tools_fts WHERE rowid = ?",
            (self._ids[name],),
        ).fetchone()
        return " ".join(part for part in row if part)

    def _store_vectors(self, ids: list[int], vectors: list[list[float]]) -> None:
        import sqlite_vec

        dim = len(vectors[0])
        stored = self._conn.execute("SELECT value FROM index_meta WHERE key='dim'").fetchone()
        with self._conn:
            if stored is not None and int(stored[0]) != dim:
                self._conn.execute("DROP TABLE IF EXISTS tools_vec")
                self._conn.execute("UPDATE tools_meta SET embedded = 0")
            if not self._table_exists("tools_vec"):
                self._conn.execute(
                    f"CREATE VIRTUAL TABLE tools_vec USING vec0(embedding float[{dim}] "
                    "distance_metric=cosine)"
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO index_meta(key, value) VALUES ('dim', ?)", (str(dim),)
                )
            for id_, vector in zip(ids, vectors, strict=True):
                self._conn.execute("DELETE FROM tools_vec WHERE rowid = ?", (id_,))
                self._conn.execute(
                    "INSERT INTO tools_vec(rowid, embedding) VALUES (?, ?)",
                    (id_, sqlite_vec.serialize_float32(vector)),
                )
                self._conn.execute("UPDATE tools_meta SET embedded = 1 WHERE id = ?", (id_,))

    def _table_exists(self, name: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone()
        return row is not None

    # -- search ------------------------------------------------------------------------------

    def search(
        self, query: str, allowed: Collection[str] | None = None, limit: int | None = None
    ) -> SearchResult:
        limit = limit or self._settings.top_k
        with self._lock:
            tokens = content_tokens(query)
            lexical, matched, named = self._lexical(tokens)
            similarity = self._semantic(query)

        qualifying_vec = {
            id_: sim for id_, sim in similarity.items() if sim >= self._settings.min_similarity
        }
        candidates = set(lexical) | set(qualifying_vec)
        if allowed is not None:
            allowed_set = set(allowed)
            candidates = {i for i in candidates if self._names.get(i) in allowed_set}

        scores: dict[int, float] = dict.fromkeys(candidates, 0.0)
        for rank, id_ in enumerate(i for i in lexical if i in candidates):
            scores[id_] += 1.0 / (_RRF_K + rank + 1)
        vec_order = sorted(
            (i for i in qualifying_vec if i in candidates), key=lambda i: -similarity[i]
        )
        for rank, id_ in enumerate(vec_order):
            scores[id_] += 1.0 / (_RRF_K + rank + 1)

        ordered = sorted(candidates, key=lambda i: -scores[i])
        total = max(len(tokens), 1)
        hits = tuple(
            Hit(
                self._names[i],
                scores[i],
                matched.get(i, 0) / total,
                similarity.get(i),
                matched.get(i, 0),
                i in named,
            )
            for i in ordered[:limit]
        )
        return SearchResult(hits, self._confidence(hits))

    def _lexical(self, tokens: list[str]) -> tuple[list[int], dict[int, int], set[int]]:
        if not tokens:
            return [], {}, set()
        combined = " OR ".join(f'"{t}"' for t in tokens)
        try:
            ranked = [
                r[0]
                for r in self._conn.execute(
                    "SELECT rowid FROM tools_fts WHERE tools_fts MATCH ? "
                    "ORDER BY bm25(tools_fts, 6.0, 2.0, 3.0, 1.0, 4.0) LIMIT ?",
                    (combined, _CANDIDATES),
                )
            ]
            matches: dict[int, int] = {}
            named: set[int] = set()
            for token in tokens:
                for (rowid,) in self._conn.execute(
                    "SELECT rowid FROM tools_fts WHERE tools_fts MATCH ?", (f'"{token}"',)
                ):
                    matches[rowid] = matches.get(rowid, 0) + 1
                named.update(
                    rowid
                    for (rowid,) in self._conn.execute(
                        "SELECT rowid FROM tools_fts WHERE tools_fts MATCH ?", (f'name:"{token}"',)
                    )
                )
        except sqlite3.Error as exc:
            log.warning("keyword search failed: %s", exc)
            return [], {}, set()
        return ranked, matches, named

    def _semantic(self, query: str) -> dict[int, float]:
        if (
            not (self._vectors_ready and self._embeddings)
            or time.monotonic() < self._vector_retry_at
        ):
            return {}
        import sqlite_vec

        try:
            vector = self._embeddings.embed_query(query)
            rows = self._conn.execute(
                "SELECT rowid, distance FROM tools_vec WHERE embedding MATCH ? AND k = ?",
                (sqlite_vec.serialize_float32(vector), _CANDIDATES),
            ).fetchall()
        except Exception as exc:
            log.warning("vector search failed, falling back to keywords: %s", exc)
            self._vector_retry_at = time.monotonic() + _VECTOR_RETRY_SECONDS
            return {}
        return {int(rowid): 1.0 - float(distance) for rowid, distance in rows}

    def _confidence(self, hits: tuple[Hit, ...]) -> Confidence:
        if not hits:
            return Confidence.NONE
        cfg = self._settings
        vectors = self._vectors_ready and any(h.similarity is not None for h in hits)
        for hit in hits:
            sim = hit.similarity or 0.0
            # Keyword-only: a query term inside the tool's name, or several matching terms, is a real
            # hit (a single generic word like "today" matching a keyword is not). With vectors, any
            # keyword match corroborated by similarity is enough: wrongly skipping a tool is worse
            # than asking the executor, which can still answer "no tool fits".
            lexical = hit.name_match or (
                hit.matched_terms >= 2 and hit.coverage >= cfg.min_coverage
            )
            if vectors:
                corroborated = hit.matched_terms >= 1 and sim >= cfg.corroborated_similarity
                if (
                    sim >= cfg.strong_similarity
                    or (lexical and sim >= cfg.min_similarity)
                    or corroborated
                ):
                    return Confidence.STRONG
            elif lexical:
                return Confidence.STRONG
        return Confidence.WEAK
