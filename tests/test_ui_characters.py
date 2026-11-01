"""Character packs: loading, fallbacks, the example template and switching the pet's look."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, QSettings
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from assistant.config import AppPaths
from assistant.ui.app import DesktopPet
from assistant.ui.characters import EXPRESSIONS, CharacterError, discover, load_character
from assistant.ui.config_store import ConfigStore
from assistant.ui.pet import PET_SIZE, draw_pet, write_example_character
from assistant.ui.settings_dialog import SettingsDialog
from assistant.ui.state import Emotion, Mood


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def picture(path: Path, color: str, size: int = 64) -> None:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    assert image.save(str(path))


@pytest.fixture
def pack(qapp, tmp_path) -> Path:
    folder = tmp_path / "characters" / "kiko"
    folder.mkdir(parents=True)
    picture(folder / "neutral.png", "#ff0000")
    return folder


def test_a_pack_with_only_neutral_works_for_every_mood_and_emotion(pack):
    sprites = load_character(pack)
    neutral = sprites.images["neutral"]
    for mood in Mood:
        for emotion in Emotion:
            assert sprites.pixmap_for(mood, emotion).cacheKey() == neutral.cacheKey()


def test_missing_expressions_fall_back_to_the_closest_one(pack):
    picture(pack / "happy.png", "#00ff00")
    picture(pack / "sleeping.png", "#0000ff")
    sprites = load_character(pack)
    assert (
        sprites.pixmap_for(Mood.IDLE, Emotion.LOVE).cacheKey() == sprites.images["happy"].cacheKey()
    )
    assert (
        sprites.pixmap_for(Mood.IDLE, Emotion.SLEEPY).cacheKey()
        == sprites.images["sleeping"].cacheKey()
    )
    # the mood picks the picture when there is no emotion override
    picture(pack / "thinking.png", "#ffff00")
    assert load_character(pack).pixmap_for(Mood.THINKING, Emotion.NEUTRAL).toImage().pixelColor(
        1, 1
    ) == QColor("#ffff00")


def test_the_display_name_comes_from_character_yaml(pack):
    (pack / "character.yaml").write_text("name: Kiko the Fox\n", encoding="utf-8")
    assert load_character(pack).name == "Kiko the Fox"


def test_broken_packs_are_reported_clearly(tmp_path, qapp):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(CharacterError, match="neutral"):
        load_character(empty)
    (empty / "neutral.png").write_text("not an image", encoding="utf-8")
    with pytest.raises(CharacterError, match="readable"):
        load_character(empty)
    with pytest.raises(CharacterError, match="not found"):
        load_character(tmp_path / "missing")


def test_discover_lists_only_folders_with_a_neutral_image(pack, tmp_path):
    (tmp_path / "characters" / "junk").mkdir()
    (tmp_path / "characters" / "readme.txt").write_text("x", encoding="utf-8")
    assert list(discover(tmp_path / "characters")) == ["kiko"]


def test_the_example_template_is_a_complete_loadable_pack(qapp, tmp_path):
    folder = tmp_path / "characters" / "example"
    written = write_example_character(folder)
    assert sorted(written) == sorted(f"{name}.png" for name in EXPRESSIONS)
    sprites = load_character(folder)
    assert set(sprites.images) == set(EXPRESSIONS)
    assert sprites.name == "Example Robot"
    assert not sprites.images["neutral"].toImage().pixelColor(0, 0).alpha()  # transparent corner


@pytest.mark.parametrize("emotion", list(Emotion))
def test_every_emotion_draws_with_a_pack(qapp, tmp_path, emotion):
    sprites = load_character(_example(tmp_path))
    image = QImage(PET_SIZE, PET_SIZE, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    draw_pet(
        painter, QRectF(0, 0, PET_SIZE, PET_SIZE), Mood.TALKING, emotion=emotion, age=12,
        look=(1, 0.5), lift=5, squash=0.1, sprites=sprites,
    )  # fmt: skip
    painter.end()
    opaque = sum(
        1
        for x in range(0, PET_SIZE, 4)
        for y in range(0, PET_SIZE, 4)
        if image.pixelColor(x, y).alpha()
    )
    assert opaque > 40


def _example(tmp_path: Path) -> Path:
    folder = tmp_path / "characters" / "example"
    if not folder.exists():
        write_example_character(folder)
    return folder


# -- switching the pet's look ------------------------------------------------------------------------


@pytest.fixture
def desktop(qapp, tmp_path):
    paths = AppPaths(tmp_path / "config", tmp_path / "data")
    paths.ensure()
    pet = DesktopPet(
        qapp,
        lambda: None,  # type: ignore[arg-type, return-value]
        settings=QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat),
        config_store=ConfigStore(paths.config_file),
        paths=paths,
    )
    yield pet, paths
    pet.pet.close()


def test_selecting_a_character_changes_and_remembers_it(desktop):
    pet, paths = desktop
    write_example_character(paths.characters_dir / "example")
    pet.select_character("example")
    assert pet.pet._sprites is not None and pet.pet._sprites.name == "Example Robot"
    assert pet._qsettings.value("pet/character") == "example"
    pet.select_character("")
    assert pet.pet._sprites is None and pet._qsettings.value("pet/character") == ""


def test_unknown_or_hostile_names_are_refused(desktop):
    pet, paths = desktop
    write_example_character(paths.characters_dir / "example")
    for name in ("nope", "../config", "..", "example/../../x"):
        pet.select_character(name)
        assert pet.pet._sprites is None  # nothing was loaded
        assert pet._qsettings.value("pet/character", "") != name


def test_settings_page_lists_characters_and_reports_the_choice(qapp, tmp_path):
    paths = AppPaths(tmp_path / "config", tmp_path / "data")
    paths.ensure()
    dialog = SettingsDialog(ConfigStore(paths.config_file), paths, auto_check=False)
    combo = dialog._character_combo

    def values():
        return [combo.itemData(i) for i in range(combo.count())]

    assert values()[0] == "" and "builtin:nexo" in values()  # the built-ins come first
    assert "mine" not in values()
    write_example_character(paths.characters_dir / "mine")
    dialog._reload_characters()
    assert values()[-1] == "mine"
    chosen = []
    dialog.character_selected.connect(chosen.append)
    combo.setCurrentIndex(values().index("mine"))
    dialog._save()
    assert chosen == ["mine"]
    dialog.close()
