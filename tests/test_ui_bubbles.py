"""Assistant messages that carry raw tool output are shown as tables / JSON, not as Markdown."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from assistant.domain import FinalEvent, TokenEvent
from assistant.ui.chat import ChatWindow, _AutoText, _Bubble, _OutputTable

SAMPLE = "Name UsedGB FreeGB\n---- ------ ------\nC     224.4    6.4\nD     192.2   52.3\nE         0      0"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def bubble(text: str) -> _Bubble:
    b = _Bubble("assistant", text)
    b.finalize()
    return b


def test_verbatim_table_message_becomes_a_table(qapp):
    b = bubble(SAMPLE)
    tables = b.findChildren(_OutputTable)
    assert len(tables) == 1 and tables[0].rowCount() == 3
    assert tables[0].item(1, 2).text() == "52.3"


def test_original_output_message_gets_a_caption_and_a_monospace_body(qapp):
    log = "line one\nline two\n  indented line"
    b = bubble(f"Original output of read_file:\n\n{log}")
    captions = [lbl.text() for lbl in b.findChildren(QLabel) if lbl.objectName() == "caption"]
    assert captions == ["Original output of read_file"]
    mono = [v for v in b.findChildren(_AutoText) if v.property("mono")]
    assert mono and mono[0].toPlainText() == log  # line breaks and indentation kept


def test_json_message_is_pretty_printed(qapp):
    b = bubble('{"a":1,"b":{"c":2}}')
    mono = [v for v in b.findChildren(_AutoText) if v.property("mono")]
    assert mono and '"c": 2' in mono[0].toPlainText()


def test_ordinary_replies_stay_markdown(qapp):
    b = bubble("Drive C has **6.4 GB** free.\n\n- D has 52.3 GB")
    assert not b.findChildren(_OutputTable)
    assert len(b.findChildren(_AutoText)) == 1 and not b.findChildren(_AutoText)[0].property("mono")


def test_final_event_converts_the_streamed_bubble(qapp):
    chat = ChatWindow("Test")
    chat.set_ready(1)
    chat.handle_event(TokenEvent(text=SAMPLE))
    assert not chat.findChildren(_OutputTable)  # still streaming as plain text
    chat.handle_event(FinalEvent(text=SAMPLE))
    assert len(chat.findChildren(_OutputTable)) == 1


def test_long_output_scrolls_inside_a_capped_box(qapp):
    from assistant.ui.chat import _build_output

    box = _build_output("\n".join(f"line {i}" for i in range(500)), limit=None)
    view = next(v for v in box.findChildren(_AutoText) if v.property("mono"))
    box.resize(360, 400)
    box.show()
    qapp.processEvents()
    assert view.height() <= _AutoText.MONO_MAX_HEIGHT
    assert view.verticalScrollBar().maximum() > 0  # the rest is reachable by scrolling
