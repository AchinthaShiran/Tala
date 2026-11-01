"""The pet notices the battery: tired when low, cheerful when plugged in, and says so."""

from __future__ import annotations

import os
import time

import pytest

from assistant.ui.system import PowerStatus, PowerWatcher

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QSettings
from PySide6.QtWidgets import QApplication

from assistant.ui.notice import NoticeBubble
from assistant.ui.pet import PetWidget
from assistant.ui.state import Emotion


def on_battery(percent: int) -> PowerStatus:
    return PowerStatus(percent, plugged_in=False)


def plugged(percent: int) -> PowerStatus:
    return PowerStatus(percent, plugged_in=True)


def kinds(notices) -> list[str]:
    return [n.kind for n in notices]


def test_no_battery_means_no_notices_and_no_tiredness():
    watcher = PowerWatcher()
    assert watcher.update(None) == [] and not watcher.tired


def test_low_battery_warns_once_and_makes_the_pet_tired():
    watcher = PowerWatcher()
    assert watcher.update(on_battery(40)) == []
    assert not watcher.tired
    assert kinds(watcher.update(on_battery(20))) == ["low"]
    assert watcher.tired
    assert watcher.update(on_battery(18)) == []  # not repeated
    assert kinds(watcher.update(on_battery(9))) == ["critical"]
    assert watcher.update(on_battery(8)) == []


def test_plugging_in_announces_it_and_ends_the_tiredness():
    watcher = PowerWatcher()
    watcher.update(on_battery(15))
    assert watcher.tired
    assert kinds(watcher.update(plugged(15))) == ["plugged"]
    assert not watcher.tired


def test_warning_comes_back_after_recovering_then_dropping_again():
    watcher = PowerWatcher()
    watcher.update(on_battery(19))
    watcher.update(plugged(50))
    watcher.update(on_battery(50))
    assert kinds(watcher.update(on_battery(19))) == ["low"]


def test_unplugging_and_full_are_announced_once():
    watcher = PowerWatcher()
    watcher.update(plugged(99))
    assert kinds(watcher.update(plugged(100))) == ["full"]
    assert watcher.update(plugged(100)) == []
    assert kinds(watcher.update(on_battery(100))) == ["unplugged"]


def test_starting_up_low_on_battery_warns_without_a_plugged_notice():
    assert kinds(PowerWatcher().update(on_battery(12))) == ["low"]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def pump(app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def test_a_tired_pet_looks_tired_when_idle_but_reacts_when_asked(qapp, tmp_path):
    pet = PetWidget(QSettings(str(tmp_path / "p.ini"), QSettings.Format.IniFormat))
    pet.set_tired(True)
    pet._tick()
    assert pet.emotion is Emotion.TIRED
    pet.react(Emotion.CHARGING, 1.0)
    pet._tick()
    assert pet.emotion is Emotion.CHARGING
    pet.set_tired(False)
    pet._override_frames = 0
    pet._tick()
    assert pet.emotion is Emotion.NEUTRAL
    pet.close()


def test_bubble_shows_queues_and_fades_away(qapp):
    bubble = NoticeBubble()
    bubble.anchor_to(QRect(500, 500, 95, 95))
    bubble.notify("first", "low")
    assert bubble.showing and bubble.text == "first"
    bubble.notify("second", "plugged")
    assert bubble.text == "first"  # waits its turn
    bubble.dismiss()
    pump(qapp, 0.5)
    assert bubble.showing and bubble.text == "second"
    bubble.clear()
    pump(qapp, 0.5)
    assert not bubble.isVisible()


def test_clicking_the_bubble_dismisses_and_signals(qapp):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    bubble = NoticeBubble()
    clicks = []
    bubble.clicked.connect(lambda: clicks.append(True))
    bubble.anchor_to(QRect(500, 500, 95, 95))
    bubble.notify("hello")
    point = QPointF(10, 10)
    bubble.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            point,
            point,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert clicks == [True]
    pump(qapp, 0.4)
    assert not bubble.isVisible()
