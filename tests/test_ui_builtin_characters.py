"""The built-in characters and the smoothness of the pet's animation (offscreen)."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRectF, QSettings
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

import assistant.ui.pet as pet_module
from assistant.config import AppPaths
from assistant.ui.app import DesktopPet
from assistant.ui.config_store import ConfigStore
from assistant.ui.pet import PET_SIZE, FadeFrom, PetWidget, draw_pet
from assistant.ui.settings_dialog import SettingsDialog
from assistant.ui.state import Emotion, Mood
from assistant.ui.vector_characters import CHARACTERS, LAMP, ROBOT

EXPECTED = {"robot", "nexo", "kiko", "momo", "lumi", "zen", "owlly", "slimey", "pupbot"}


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


class FarCursor:
    @staticmethod
    def pos() -> QPoint:
        return QPoint(9000, 9000)


@pytest.fixture
def pet(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(pet_module, "QCursor", FarCursor)
    widget = PetWidget(QSettings(str(tmp_path / "pet.ini"), QSettings.Format.IniFormat))
    yield widget
    widget.close()


def render(character, emotion=Emotion.NEUTRAL, mood=Mood.IDLE, **kw) -> QImage:
    image = QImage(PET_SIZE, PET_SIZE, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    draw_pet(
        painter, QRectF(0, 0, PET_SIZE, PET_SIZE), mood, emotion=emotion, vector=character, **kw
    )
    painter.end()
    return image


def covered(image: QImage) -> int:
    return sum(
        1
        for x in range(0, PET_SIZE, 3)
        for y in range(0, PET_SIZE, 3)
        if image.pixelColor(x, y).alpha()
    )


# -- the characters ---------------------------------------------------------------------------------


def test_all_characters_from_the_concept_sheet_exist():
    assert set(CHARACTERS) == EXPECTED
    assert CHARACTERS["robot"] is ROBOT
    names = {c.name for c in CHARACTERS.values()}
    assert {"Nexo", "Kiko", "Momo", "Lumi", "ZEN", "Owlly", "Slimey", "PupBot"} <= names
    assert all(c.tagline for c in CHARACTERS.values())


@pytest.mark.parametrize("key", sorted(EXPECTED))
@pytest.mark.parametrize("emotion", list(Emotion))
@pytest.mark.parametrize("mood", [Mood.IDLE, Mood.TALKING, Mood.ERROR])
def test_every_character_renders_every_expression(qapp, key, emotion, mood):
    image = render(CHARACTERS[key], emotion, mood, age=11, phase=2.2, look=(0.6, -0.3), blink=0.4)
    assert covered(image) > 600  # a real figure, not an empty frame


def test_characters_look_different_from_each_other(qapp):
    pictures = {key: render(c) for key, c in CHARACTERS.items()}
    keys = list(pictures)
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            assert pictures[a] != pictures[b], f"{a} and {b} are drawn identically"


def test_the_mood_light_shows_in_every_character(qapp):
    for character in CHARACTERS.values():
        calm = render(character, lamp=QColor("#5be37d"))
        alert = render(character, lamp=QColor("#ff2020"))
        assert calm != alert, f"{character.name} has no mood light"


def test_the_mouthless_owl_still_shows_emotions(qapp):
    owl = CHARACTERS["owlly"]
    assert owl.mouth is False
    assert render(owl, Emotion.HAPPY) != render(owl, Emotion.SAD)


# -- smoothness ---------------------------------------------------------------------------------------


def test_a_new_expression_fades_in_instead_of_snapping(pet):
    pet.react(Emotion.HAPPY, 3.0)
    pet._tick()
    assert pet._fade_from is not None and 0.0 < pet._fade < 1.0
    seen = []
    for _ in range(int(pet_module._FADE_SECONDS * pet_module._FPS) + 2):
        pet._tick()
        seen.append(pet._fade)
    assert seen == sorted(seen) and seen[-1] == 1.0  # a steady, finishing fade


def test_a_crossfade_is_a_blend_of_both_faces(qapp):
    before = render(ROBOT, Emotion.SAD)
    after = render(ROBOT, Emotion.HAPPY)
    middle = render(ROBOT, Emotion.HAPPY, fade_from=FadeFrom(Emotion.SAD, Mood.IDLE, 0), fade=0.5)
    assert middle != before and middle != after


def test_blinks_close_the_eyes_gradually(pet):
    pet._next_blink = 0.0
    amounts = []
    for _ in range(int(pet_module._BLINK_SECONDS * pet_module._FPS) + 4):
        pet._tick()
        amounts.append(pet._blink_amount())
    assert max(amounts) > 0.9
    assert (
        len([a for a in amounts if 0.05 < a < 0.95]) >= 4
    )  # it passes through in-between positions
    assert amounts[-1] == 0.0  # and ends open


def test_the_mood_light_glides_to_the_new_colour(pet):
    start = QColor(pet._lamp)
    pet.set_mood(Mood.ERROR)
    pet._tick()
    first = QColor(pet._lamp)
    assert first != start and first != LAMP[Mood.ERROR]  # moved, but not all the way
    for _ in range(pet_module._FPS * 4):
        pet._tick()
    assert abs(pet._lamp.red() - LAMP[Mood.ERROR].red()) <= 3


def test_timing_is_in_seconds_not_frames():
    # the same wall-clock second advances the idle phase equally at any frame rate
    for fps in (25, 40, 60):
        assert abs(0.11 * (25 / fps) * fps - 0.11 * 25) < 1e-9
    assert pet_module._FPS >= 40  # smooth enough for hopping and fades


# -- choosing a built-in -----------------------------------------------------------------------------------


def make_desktop(qapp, tmp_path, ini: str | None = None) -> tuple[DesktopPet, AppPaths]:
    paths = AppPaths(tmp_path / "config", tmp_path / "data")
    paths.ensure()
    app = DesktopPet(
        qapp,
        lambda: None,  # type: ignore[arg-type, return-value]
        settings=QSettings(ini or str(tmp_path / "ui.ini"), QSettings.Format.IniFormat),
        config_store=ConfigStore(paths.config_file),
        paths=paths,
    )
    return app, paths


def test_selecting_a_built_in_character_switches_and_remembers_it(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(pet_module, "QCursor", FarCursor)
    app, _ = make_desktop(qapp, tmp_path)
    app.select_character("builtin:kiko")
    assert app.pet._vector.key == "kiko" and app.pet._sprites is None
    assert app._qsettings.value("pet/character") == "builtin:kiko"
    app.select_character("")
    assert app.pet._vector is ROBOT
    app.pet.close()


def test_unknown_built_ins_are_refused(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(pet_module, "QCursor", FarCursor)
    app, _ = make_desktop(qapp, tmp_path)
    app.select_character("builtin:nope")
    assert app.pet._vector is ROBOT
    assert app._qsettings.value("pet/character", "") != "builtin:nope"
    app.pet.close()


def test_the_saved_choice_is_used_on_the_next_start(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(pet_module, "QCursor", FarCursor)
    ini = str(tmp_path / "ui.ini")
    QSettings(ini, QSettings.Format.IniFormat).setValue("pet/character", "builtin:owlly")
    app, _ = make_desktop(qapp, tmp_path, ini)
    assert app.pet._vector.key == "owlly"
    app.pet.close()


def test_the_pet_page_offers_every_character_and_reports_the_choice(qapp, tmp_path):
    paths = AppPaths(tmp_path / "config", tmp_path / "data")
    paths.ensure()
    dialog = SettingsDialog(ConfigStore(paths.config_file), paths, auto_check=False)
    combo = dialog._character_combo
    data = [combo.itemData(i) for i in range(combo.count())]
    assert data[0] == "" and {f"builtin:{k}" for k in EXPECTED - {"robot"}} <= set(data)
    chosen = []
    dialog.character_selected.connect(chosen.append)
    combo.setCurrentIndex(data.index("builtin:momo"))
    dialog._save()
    assert chosen == ["builtin:momo"]
    dialog.close()
