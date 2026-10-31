"""Turns raw tool output into something nicer to look at (no Qt, so it is unit-testable).

The default schema, tried in this order:

1. **JSON**: pretty-printed with indentation.
2. **Underlined tables**: a header line followed by a line of dashes, as printed by PowerShell's
   ``Format-Table`` (``Name  UsedGB`` / ``----  ------``). Column positions come from the dashes.
3. **Tab-separated** text: every line has the same number of tabs.
4. **Whitespace-aligned tables**: three or more lines with the same number of words and some
   numbers in the rows (``df``, ``tasklist``, ``ps``).
5. Anything else stays plain monospace text, untouched.

The raw output is never altered; this only chooses how to display it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

MAX_TABLE_ROWS = 200
_DASHES = re.compile(r"^\s*-+(?:\s+-+)*\s*$")
_NUMBER = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?%?$")
_MAX_COLUMNS = 12


@dataclass(frozen=True, slots=True)
class TableOutput:
    headers: list[str]
    rows: list[list[str]]
    hidden_rows: int = 0  # rows beyond MAX_TABLE_ROWS that are not shown

    @property
    def numeric(self) -> list[bool]:
        """Columns whose every non-empty cell is a number (they are right-aligned)."""
        flags: list[bool] = []
        for index in range(len(self.headers)):
            cells = [row[index] for row in self.rows if index < len(row) and row[index]]
            flags.append(bool(cells) and all(_is_number(cell) for cell in cells))
        return flags


@dataclass(frozen=True, slots=True)
class TextOutput:
    text: str
    kind: str = "text"  # "text" | "json"


def parse_output(raw: str) -> TableOutput | TextOutput:
    text = raw.replace("\r\n", "\n").strip("\n")
    stripped = text.strip()
    if not stripped:
        return TextOutput("")
    if stripped[0] in "[{":
        pretty = _pretty_json(stripped)
        if pretty is not None:
            return TextOutput(pretty, "json")
    lines = [line.rstrip() for line in text.split("\n")]
    return (
        _underlined_table(lines)
        or _tab_table(lines)
        or _whitespace_table(lines)
        or TextOutput(text)
    )


def _pretty_json(text: str) -> str | None:
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        return None


def _is_number(cell: str) -> bool:
    return bool(cell) and cell != "." and bool(_NUMBER.match(cell))


def _build(headers: list[str], rows: list[list[str]]) -> TableOutput:
    width = len(headers)
    padded = [(row + [""] * width)[:width] for row in rows]
    hidden = max(0, len(padded) - MAX_TABLE_ROWS)
    return TableOutput(headers, padded[:MAX_TABLE_ROWS], hidden)


def _underlined_table(lines: list[str]) -> TableOutput | None:
    content = [i for i, line in enumerate(lines) if line.strip()]
    if len(content) < 2 or content[0] != 0 or not _DASHES.match(lines[content[1]]):
        return None
    header, underline = lines[content[0]], lines[content[1]]
    starts = [m.start() for m in re.finditer(r"-+", underline)]
    if len(starts) < 2 and not header.strip():
        return None
    bounds = [*starts, max(len(line) for line in lines) + 1]

    def cut(line: str) -> list[str]:
        return [line[bounds[i] : bounds[i + 1]].strip() for i in range(len(starts))]

    if any(_splits_a_word(lines[i], starts[1:]) for i in content):
        return None  # not really column-aligned: let the word-based reader try instead
    rows = [cut(lines[i]) for i in content[2:]]
    return _build(cut(header), rows) if rows else None


def _splits_a_word(line: str, boundaries: list[int]) -> bool:
    """True if a column boundary falls inside a word of this line."""
    return any(0 < b < len(line) and line[b - 1] != " " and line[b] != " " for b in boundaries)


def _tab_table(lines: list[str]) -> TableOutput | None:
    content = [line for line in lines if line.strip()]
    counts = {line.count("\t") for line in content}
    if len(content) < 2 or len(counts) != 1 or counts == {0}:
        return None
    cells = [[c.strip() for c in line.split("\t")] for line in content]
    return _build(cells[0], cells[1:])


def _whitespace_table(lines: list[str]) -> TableOutput | None:
    content = [line.split() for line in lines if line.strip() and not _DASHES.match(line)]
    if len(content) < 3:
        return None
    width = len(content[0])
    if not 2 <= width <= _MAX_COLUMNS or any(len(words) != width for words in content):
        return None
    header, rows = content[0], content[1:]
    if any(_is_number(word) for word in header):  # a header names things; it is not data
        return None
    if not any(_is_number(word) for row in rows for word in row):
        return None  # no numbers: more likely a list of words than a table
    return _build(header, rows)
