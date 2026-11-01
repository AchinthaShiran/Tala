"""Desktop pet: mood mapping (pure) and an offscreen end-to-end run against scripted models."""

from __future__ import annotations

import os
import time

import pytest

from assistant.domain import (
    ApprovalMode,
    ApprovalRequest,
    ApprovalRequestedEvent,
    ErrorEvent,
    FinalEvent,
    RiskLevel,
    TokenEvent,
    ToolProposedEvent,
)
from assistant.ui.state import Mood, mood_for
from tests.support import ai, tool_call


def test_mood_follows_the_event_stream():
    request = ApprovalRequest(
        call_id="1",
        tool="docker_stop",
        arguments={},
        risk=RiskLevel.MUTATING,
        mode=ApprovalMode.ASK,
        command="docker stop web",
    )
    proposed = ToolProposedEvent(
        call_id="1", tool="t", arguments={}, risk=RiskLevel.READ_ONLY, command="c"
    )
    assert mood_for(TokenEvent(text="hi")) is Mood.TALKING
    assert mood_for(proposed) is Mood.THINKING
    assert mood_for(ApprovalRequestedEvent(requests=[request])) is Mood.ASKING
    assert mood_for(ErrorEvent(message="x")) is Mood.ERROR
    assert mood_for(FinalEvent(text="x")) is Mood.IDLE


# -- Qt (skipped when PySide6 is not installed) ---------------------------------------------------

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from assistant.ui.app import DesktopPet  # noqa: E402
from assistant.ui.chat import ChatWindow, _ApprovalCard, _Bubble, _ToolRow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def wait_for(app, condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached in time")


def bubbles(chat: ChatWindow, role: str) -> list[str]:
    return [b.text_content for b in chat.findChildren(_Bubble) if b.objectName() == role]


@pytest.fixture
def pet(qapp, make_harness, tmp_path):
    scripts = {
        "executor": [ai("", tool_call("docker_stop", {"container": "web"})), ai("DONE")],
        "summarizer": ["Stopped web."],
        "chat": ["Hello there!"],
    }
    # Built on the worker thread: the runtime's SQLite connections must live where they are used.
    desktop = DesktopPet(
        qapp,
        lambda: make_harness(scripts).runtime,
        settings=QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat),
    )
    desktop.start()
    wait_for(qapp, lambda: desktop.chat._ready)
    yield desktop
    desktop.quit()


def test_chat_round_trip_streams_into_a_bubble(qapp, pet):
    pet.chat._input.setText("hello")
    pet.chat._submit()
    assert not pet.chat._input.isEnabled()  # one request at a time
    wait_for(qapp, lambda: pet.chat._input.isEnabled())

    assert bubbles(pet.chat, "user") == ["hello"]
    assert "Hello there!" in bubbles(pet.chat, "assistant")
    assert pet.pet.mood is Mood.IDLE


def test_tool_approval_card_runs_the_tool_after_approve(qapp, pet):
    pet.chat._input.setText("stop the docker container web")
    pet.chat._submit()
    wait_for(qapp, lambda: pet.chat.findChildren(_ApprovalCard))

    assert pet.pet.mood is Mood.ASKING
    assert pet.chat.isVisible() and not pet.chat._input.isEnabled()  # approval pops the chat open
    card = pet.chat.findChildren(_ApprovalCard)[0]
    assert "docker" in card._request.command
    allow = next(b for b in card.findChildren(QPushButton) if b.text() == "Approve")
    allow.click()

    wait_for(qapp, lambda: pet.chat._input.isEnabled())
    assert "Stopped web." in bubbles(pet.chat, "assistant")
    assert pet.pet.mood is Mood.IDLE


def test_deny_does_not_run_the_tool(qapp, pet):
    pet.chat._input.setText("stop the docker container web")
    pet.chat._submit()
    wait_for(qapp, lambda: pet.chat.findChildren(_ApprovalCard))
    card = pet.chat.findChildren(_ApprovalCard)[0]
    next(b for b in card.findChildren(QPushButton) if b.text() == "Deny").click()
    wait_for(qapp, lambda: pet.chat._input.isEnabled())
    rows = [t.status for t in pet.chat.findChildren(_ToolRow)]
    assert rows and "ok" not in rows  # proposed, never executed


def test_confirm_mode_requires_typing_the_tool_name(qapp):
    request = ApprovalRequest(
        call_id="9",
        tool="delete_file",
        arguments={},
        risk=RiskLevel.DESTRUCTIVE,
        mode=ApprovalMode.CONFIRM,
        command="rm x",
        message="Cannot be undone",
    )
    card = _ApprovalCard(request)
    allow = next(b for b in card.findChildren(QPushButton) if b.text() == "Approve")
    assert not allow.isEnabled()
    card._typed.setText("delete_file")
    assert allow.isEnabled()
    seen = []
    card.decided.connect(lambda cid, ok: seen.append((cid, ok)))
    allow.click()
    assert seen == [("9", True)]


def test_assistant_text_cannot_open_links(qapp):
    bubble = _Bubble("assistant", "[click](https://example.com)")
    assert not bubble.openExternalLinks()


def test_tool_output_renders_as_a_table_and_can_be_copied(qapp):
    from PySide6.QtWidgets import QApplication as App

    from assistant.ui.chat import _OutputTable, _ToolRow

    proposed = ToolProposedEvent(
        call_id="1", tool="disk_free", arguments={}, risk=RiskLevel.READ_ONLY, command="c"
    )
    row = _ToolRow(proposed)
    from assistant.domain import ToolResultEvent

    text = "Name UsedGB FreeGB\n---- ------ ------\nC 224.4 6.4\nD 192.2 52.3\n"
    row.finish(ToolResultEvent(call_id="1", tool="disk_free", status="ok", output=text))
    tables = row.findChildren(_OutputTable)
    assert len(tables) == 1 and tables[0].rowCount() == 2 and tables[0].columnCount() == 3
    assert tables[0].item(0, 1).text() == "224.4"
    row._copy.click()
    assert App.clipboard().text() == text.strip()


def test_battery_readings_drive_the_pet_and_the_bubble(qapp, pet):
    from assistant.ui.state import Emotion
    from assistant.ui.system import PowerStatus

    pet._power_reader = lambda: PowerStatus(15, plugged_in=False)
    pet.check_power()
    assert pet.bubble.showing and "15%" in pet.bubble.text
    assert pet.pet._tired
    pet._power_reader = lambda: PowerStatus(15, plugged_in=True)
    pet.check_power()
    assert not pet.pet._tired
    assert pet.pet._override is Emotion.CHARGING


def test_battery_alerts_can_be_turned_off(qapp, pet):
    pet._set_battery_alerts(False)
    pet._power_reader = lambda: __import__("assistant.ui.system", fromlist=["x"]).PowerStatus(
        5, False
    )
    pet.check_power()
    assert not pet.pet._tired and not pet.bubble.showing
