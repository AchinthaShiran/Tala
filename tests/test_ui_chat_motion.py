"""The chat window fades in and out and glides to new messages."""

from __future__ import annotations

import os
import time

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from assistant.domain import TokenEvent
from assistant.ui.chat import ChatWindow

PET = QRect(900, 600, 150, 150)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def pump(app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def test_opening_fades_in(qapp):
    chat = ChatWindow("Test")
    chat.present(PET)
    assert chat.is_open and chat.windowOpacity() < 1.0  # starts transparent
    pump(qapp, 0.4)
    assert chat.windowOpacity() == pytest.approx(1.0)
    chat.close()


def test_hiding_fades_out_then_hides_and_announces_it(qapp):
    chat = ChatWindow("Test")
    hidden = []
    chat.hidden_by_user.connect(lambda: hidden.append(True))
    chat.present(PET)
    pump(qapp, 0.3)
    chat.hide_chat()
    assert chat.isVisible() and not chat.is_open and not hidden  # on its way out
    pump(qapp, 0.4)
    assert not chat.isVisible() and hidden == [True]
    assert chat.windowOpacity() == 1.0  # ready for next time
    chat.close()


def test_reopening_while_it_fades_out_cancels_the_close(qapp):
    chat = ChatWindow("Test")
    hidden = []
    chat.hidden_by_user.connect(lambda: hidden.append(True))
    chat.present(PET)
    pump(qapp, 0.3)
    chat.hide_chat()
    pump(qapp, 0.03)
    chat.present(PET)
    pump(qapp, 0.4)
    assert chat.is_open and hidden == [] and chat.windowOpacity() == pytest.approx(1.0)
    chat.close()


def test_new_messages_glide_into_view_and_following_survives_it(qapp):
    chat = ChatWindow("Test")
    chat.set_ready(1)
    chat.present(PET)
    pump(qapp, 0.3)
    bar = chat._scroll.verticalScrollBar()
    for i in range(40):
        chat.add_note(f"message number {i} " * 6)
    pump(qapp, 0.6)
    assert bar.maximum() > 0 and bar.value() >= bar.maximum() - 6  # at the newest message
    chat.handle_event(TokenEvent(text="a fresh reply " * 20))
    pump(qapp, 0.4)
    assert bar.value() >= bar.maximum() - 6  # still following after the glide
    bar.setValue(0)  # the user scrolls up to read: stop following
    pump(qapp, 0.1)
    chat.handle_event(TokenEvent(text=" more text" * 30))
    pump(qapp, 0.4)
    assert bar.value() < bar.maximum() - 50
    chat.close()
