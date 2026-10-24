"""Query tokenisation shared by indexing and search."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

# Words that match half the tool descriptions without saying which tool is wanted.
_STOPWORD_TEXT = """
a an the and or but if of to in on at by for with from into onto over about as is are was were
be been being am do does did done have has had having i me my mine we our you your it its this
that these those there here what whats which who whom whose when where why how can could would
should will shall may might must please hi hello hey thanks thank ok okay yes no not just so
some any all more most very really also then than too up down out off again still now
show give tell display see let make get want need like use using
lot great cool nice good awesome perfect wow sure fine cheers bye goodbye morning evening night
"""
STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def content_tokens(query: str) -> list[str]:
    """Lower-cased, de-duplicated, stop-word-free tokens in their original order."""
    seen: dict[str, None] = {}
    for token in _TOKEN_RE.findall(query.lower()):
        if len(token) > 1 and token not in STOPWORDS:
            seen.setdefault(token)
    return list(seen)
