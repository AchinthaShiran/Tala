from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from assistant.config import RetrievalSettings, builtin_packs_dir
from assistant.packs import PackRoot, load_packs
from assistant.retrieval import Confidence, ToolIndex, content_tokens
from tests.support import HashEmbeddings

TOOLS = list(load_packs([PackRoot(builtin_packs_dir(), "builtin")]).tools.values())
NAMES = {t.name for t in TOOLS}


def _extensions_loadable() -> bool:
    """Some Python builds (e.g. macOS) ship sqlite3 without loadable-extension support."""
    conn = sqlite3.connect(":memory:")
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
    except (ImportError, AttributeError, sqlite3.Error):
        return False
    finally:
        conn.close()
    return True


needs_vec = pytest.mark.skipif(
    not _extensions_loadable(), reason="sqlite3 cannot load the sqlite-vec extension here"
)


@pytest.fixture
def keyword_index(tmp_path: Path) -> ToolIndex:
    index = ToolIndex(tmp_path / "i.sqlite", RetrievalSettings(), embeddings=None)
    index.sync(TOOLS)
    yield index
    index.close()


def test_content_tokens_drop_stopwords_and_duplicates():
    assert content_tokens("How much is the disk space, the DISK?") == ["much", "disk", "space"]
    assert content_tokens("hi, show me the list") == ["list"]
    assert content_tokens("") == []


def test_keyword_search_finds_the_right_tool(keyword_index):
    result = keyword_index.search("how much disk space is left")
    assert result.confidence is Confidence.STRONG
    assert result.names[0] == "disk_free"
    assert not keyword_index.vectors_enabled


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("what is my ip address", "network_config"),
        ("ping google.com", "ping_host"),
        ("which processes are running", "list_processes"),
        ("how much memory is free", "memory_usage"),
        ("is my laptop charging", "battery_status"),
    ],
)
def test_example_queries_hit_expected_tool(keyword_index, query, expected):
    assert expected in keyword_index.search(query).names[:3]


def test_chit_chat_has_no_candidates(keyword_index):
    for query in ("hello how are you", "tell me a joke about cats", "thanks!", ""):
        assert keyword_index.search(query).confidence is Confidence.NONE


def test_single_generic_word_is_only_a_weak_match(keyword_index):
    result = keyword_index.search("anything special today")
    assert result.confidence is Confidence.WEAK and result.hits


def test_allowed_filter_limits_candidates(keyword_index):
    result = keyword_index.search("disk space", allowed={"memory_usage", "uptime"})
    assert not set(result.names) - {"memory_usage", "uptime"}


def test_limit_is_respected(keyword_index):
    assert len(keyword_index.search("network ip dns ping route", limit=3).hits) <= 3


def test_special_characters_in_query_do_not_break_fts(keyword_index):
    for query in ('disk" OR *', "NEAR(a b)", "'; DROP TABLE tools_fts; --", "c:\\users\\x"):
        keyword_index.search(query)  # must not raise


def test_sync_adds_updates_and_removes(tmp_path):
    index = ToolIndex(tmp_path / "i.sqlite", RetrievalSettings())
    index.sync(TOOLS)
    assert "disk_free" in index.search("disk space").names

    index.sync([t for t in TOOLS if t.name != "disk_free"])
    assert "disk_free" not in index.search("disk space").names

    changed = next(t for t in TOOLS if t.name == "uptime").model_copy(
        update={"keywords": ("zebrafish",)}
    )
    index.sync([changed])
    assert index.search("zebrafish").names == ["uptime"]
    index.close()


def test_index_survives_reopen(tmp_path):
    first = ToolIndex(tmp_path / "i.sqlite", RetrievalSettings())
    first.sync(TOOLS)
    first.close()
    second = ToolIndex(tmp_path / "i.sqlite", RetrievalSettings())
    second.sync(TOOLS)
    assert second.search("disk space").names[0] == "disk_free"
    second.close()


# -- vector mode ---------------------------------------------------------------------------------


def settings(**kw):
    return RetrievalSettings(min_similarity=0.3, strong_similarity=0.5, **kw)


@needs_vec
def test_vector_search_enabled_and_used(tmp_path):
    emb = HashEmbeddings()
    index = ToolIndex(tmp_path / "v.sqlite", settings(), emb, embedding_id="hash64")
    index.sync(TOOLS)
    assert index.vectors_enabled
    result = index.search("how much free disk space is left on drive")
    assert result.names[0] == "disk_free"
    assert result.hits[0].similarity is not None and emb.queries
    index.close()


def test_embedding_failure_falls_back_to_keywords(tmp_path):
    index = ToolIndex(
        tmp_path / "v.sqlite", settings(), HashEmbeddings(fail=True), embedding_id="x"
    )
    index.sync(TOOLS)
    assert not index.vectors_enabled
    assert index.search("disk space").names[0] == "disk_free"
    index.close()


def test_query_time_embedding_failure_degrades_without_repeated_retries(tmp_path):
    emb = HashEmbeddings()
    index = ToolIndex(tmp_path / "v.sqlite", settings(), emb, embedding_id="x")
    index.sync(TOOLS)
    emb.fail = True
    assert index.search("disk space").names[0] == "disk_free"
    emb.fail = False
    before = len(emb.queries)
    index.search("disk space")  # within the retry cool-down: no new embedding attempt
    assert len(emb.queries) == before
    index.close()


@needs_vec
def test_changed_embedding_model_or_dimension_rebuilds_vectors(tmp_path):
    path = tmp_path / "v.sqlite"
    a = ToolIndex(path, settings(), HashEmbeddings(dim=32), embedding_id="model-a")
    a.sync(TOOLS)
    a.close()
    b = ToolIndex(path, settings(), HashEmbeddings(dim=96), embedding_id="model-b")
    b.sync(TOOLS)
    assert b.vectors_enabled
    assert b.search("disk space").names[0] == "disk_free"
    b.close()


def test_disabling_embeddings_in_settings(tmp_path):
    index = ToolIndex(
        tmp_path / "v.sqlite", RetrievalSettings(use_embeddings=False), HashEmbeddings()
    )
    index.sync(TOOLS)
    assert not index.vectors_enabled
    index.close()
