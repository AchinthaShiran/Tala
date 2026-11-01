"""The pet reacts to the pointer and shows emotions (offscreen, with a stand-in for the mouse)."""

from __future__ import annotations

import os

import pytest

from assistant.domain import ErrorEvent, FinalEvent, TokenEvent
from assistant.ui.state import Emotion, Mood, emotion_for

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSettings, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

import assistant.ui.pet as pet_module
from assistant.ui.pet import PET_SIZE, PetWidget, draw_pet


class FakeCursor:
    """Replaces QCursor so tests can put the pointer anywhere."""

    position = QPoint(0, 0)

    @classmethod
    def pos(cls) -> QPoint:
        return cls.position


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pet(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(pet_module, "QCursor", FakeCursor)
    widget = PetWidget(QSettings(str(tmp_path / "pet.ini"), QSettings.Format.IniFormat))
    widget.move(500, 500)
    FakeCursor.position = QPoint(5000, 5000)  # far away: nothing happens by default
    yield widget
    widget.close()


def centre(widget: PetWidget) -> QPoint:
    return widget.mapToGlobal(widget.rect().center())


def run(widget: PetWidget, frames: int) -> None:
    for _ in range(frames):
        widget._tick()


def mouse(kind: QEvent.Type, widget: PetWidget, at: QPoint) -> QMouseEvent:
    return QMouseEvent(
        kind,
        QPointF(widget.mapFromGlobal(at)),
        QPointF(at),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def press(widget, at):
    widget.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, widget, at))


def drag_to(widget, at):
    widget.mouseMoveEvent(mouse(QEvent.Type.MouseMove, widget, at))


def release(widget, at):
    widget.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, widget, at))


# -- following the pointer ------------------------------------------------------------------------


def test_eyes_follow_the_pointer_and_relax_when_it_is_far_away(pet):
    FakeCursor.position = centre(pet) + QPoint(300, 0)
    run(pet, 30)
    assert pet._look[0] > 0.9
    FakeCursor.position = centre(pet) + QPoint(-300, -100)
    run(pet, 30)
    assert pet._look[0] < -0.9 and pet._look[1] < 0
    FakeCursor.position = centre(pet) + QPoint(5000, 0)
    run(pet, 40)
    assert abs(pet._look[0]) < 0.05


# -- hover, petting ---------------------------------------------------------------------------------


def test_pointer_arriving_surprises_then_petting_makes_it_fall_in_love(pet):
    FakeCursor.position = centre(pet)
    run(pet, 2)
    assert pet.emotion is Emotion.SURPRISED
    run(pet, 40)  # the surprise passes; it is just curious about the pointer
    assert pet.emotion is Emotion.NEUTRAL
    run(
        pet, int(pet_module._PET_SECONDS * pet_module._FPS)
    )  # ...and after a few seconds of being petted:
    assert pet.emotion is Emotion.LOVE
    FakeCursor.position = QPoint(5000, 5000)
    run(pet, int(4.5 * pet_module._FPS))
    assert pet.emotion is Emotion.NEUTRAL


# -- click, drag, shake -------------------------------------------------------------------------------


def test_click_makes_it_hop_happy_and_emits_clicked(pet):
    seen = []
    pet.clicked.connect(lambda: seen.append(True))
    at = centre(pet)
    press(pet, at)
    release(pet, at)
    run(pet, 1)
    assert seen == [True] and pet.emotion is Emotion.HAPPY
    assert pet._lift > 0  # it is in the air


def test_dragging_surprises_it_and_putting_it_down_pleases_it(pet):
    start = centre(pet)
    press(pet, start)
    drag_to(pet, start + QPoint(40, 10))
    run(pet, 1)
    assert pet.emotion is Emotion.SURPRISED
    release(pet, start + QPoint(40, 10))
    run(pet, 1)
    assert pet.emotion is Emotion.HAPPY


def test_shaking_it_makes_it_dizzy(pet):
    start = centre(pet)
    press(pet, start)
    for i in range(12):  # quick back and forth
        drag_to(pet, start + QPoint(30 if i % 2 else -30, 0))
    run(pet, 1)
    assert pet.emotion is Emotion.DIZZY
    release(pet, start)
    run(pet, 1)
    assert pet.emotion is Emotion.DIZZY  # being put down does not cure dizziness


def test_double_click_is_delight_without_toggling_the_chat_twice(pet):
    seen = []
    pet.clicked.connect(lambda: seen.append(True))
    at = centre(pet)
    press(pet, at)
    release(pet, at)
    pet.mouseDoubleClickEvent(mouse(QEvent.Type.MouseButtonDblClick, pet, at))
    release(pet, at)  # the release after a double click has no matching press
    run(pet, 1)
    assert seen == [True] and pet.emotion is Emotion.LOVE


# -- sleeping ---------------------------------------------------------------------------------------------


def test_it_gets_sleepy_then_sleeps_and_any_attention_wakes_it(pet):
    run(pet, int(pet_module._SLEEPY_AFTER * pet_module._FPS) + 5)
    assert pet.emotion is Emotion.SLEEPY
    run(pet, int((pet_module._ASLEEP_AFTER - pet_module._SLEEPY_AFTER) * pet_module._FPS) + 5)
    assert pet.emotion is Emotion.SLEEPING
    FakeCursor.position = centre(pet)  # the pointer comes by
    run(pet, 2)
    assert pet.emotion is Emotion.SURPRISED


def test_it_does_not_fall_asleep_while_working(pet):
    pet.set_mood(Mood.THINKING)
    run(pet, int(pet_module._ASLEEP_AFTER * pet_module._FPS) + 10)
    assert pet.emotion is Emotion.NEUTRAL


# -- emotions from the assistant ---------------------------------------------------------------------------


def test_events_map_to_reactions():
    assert emotion_for(FinalEvent(text="done")) == (Emotion.HAPPY, 2.5)
    assert emotion_for(FinalEvent(text="")) is None
    assert emotion_for(TokenEvent(text="hi")) is None
    assert emotion_for(ErrorEvent(message="x")) is None  # sadness comes from the ERROR mood


def test_errors_look_sad_and_questions_look_curious_without_any_override(qapp):
    def pixels(mood, emotion=Emotion.NEUTRAL):
        image = QImage(120, 120, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        draw_pet(painter, QRectF(0, 0, 120, 120), mood, emotion=emotion)
        painter.end()
        return image

    # the mood alone picks the face: same picture as asking for that emotion explicitly
    assert pixels(Mood.ERROR) == pixels(Mood.ERROR, Emotion.SAD)
    assert pixels(Mood.ASKING) == pixels(Mood.ASKING, Emotion.CURIOUS)
    assert pixels(Mood.IDLE) != pixels(Mood.ERROR)
    assert pixels(Mood.IDLE, Emotion.HAPPY) != pixels(Mood.IDLE, Emotion.SAD)


@pytest.mark.parametrize("emotion", list(Emotion))
@pytest.mark.parametrize("mood", list(Mood))
def test_every_emotion_renders_in_every_mood(qapp, mood, emotion):
    image = QImage(PET_SIZE, PET_SIZE, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    draw_pet(
        painter,
        QRectF(0, 0, PET_SIZE, PET_SIZE),
        mood,
        emotion=emotion,
        age=17,
        phase=2.0,
        look=(0.7, -0.4),
        squash=0.1,
        lift=6,
        tilt=2,
        attention=True,
    )
    painter.end()
    opaque = sum(
        1
        for x in range(0, PET_SIZE, 5)
        for y in range(0, PET_SIZE, 5)
        if image.pixelColor(x, y).alpha()
    )
    assert opaque > 30  # something was drawn


def test_size_changes_in_place_is_remembered_and_clamped(qapp):
    from PySide6.QtCore import QSettings

    from assistant.ui.pet import PET_SIZES

    settings = QSettings("tala-test", "pet-size")
    settings.clear()
    pet = PetWidget(settings)
    assert pet.size_px == PET_SIZES["Small"]
    pet.show()
    centre = pet.geometry().center()
    pet.set_size(PET_SIZES["Tiny"])
    assert (pet.width(), pet.height()) == (PET_SIZES["Tiny"],) * 2
    assert abs(pet.geometry().center().x() - centre.x()) <= 1
    pet.set_size(99999)  # out of range: clamped
    assert pet.size_px == max(PET_SIZES.values())
    assert PetWidget(settings).size_px == max(PET_SIZES.values())  # remembered
    pet.close()
    settings.clear()
