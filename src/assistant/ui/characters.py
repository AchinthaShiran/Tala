"""Character packs: swap the built-in robot for your own artwork.

A pack is a folder with one transparent image per expression::

    characters/kiko/
        neutral.png      required: every other image is optional
        happy.png  love.png  surprised.png  sad.png  curious.png
        dizzy.png  sleepy.png  sleeping.png
        thinking.png  talking.png  blink.png
        character.yaml   optional: ``name: Kiko the Fox``

Missing expressions fall back to the closest one that exists (love -> happy -> neutral ...), so a
pack can start with just ``neutral.png``. The pet's hopping, tilting, squashing, eye-following
(a small parallax shift) and its floating hearts, "z"s and sparkles all work on top of any pack.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QPixmap

from assistant.ui.state import Emotion, Mood

CHARACTER = 120  # logical size of the drawing area (see pet.py)
EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg")
EXPRESSIONS = (
    "neutral",
    "happy",
    "love",
    "surprised",
    "sad",
    "curious",
    "dizzy",
    "sleepy",
    "sleeping",
    "tired",
    "charging",
    "thinking",
    "talking",
    "blink",
)
_MAX_SIDE = 4096
_FALLBACKS: dict[str, tuple[str, ...]] = {
    "love": ("happy",),
    "happy": (),
    "surprised": (),
    "sad": (),
    "curious": (),
    "dizzy": ("surprised",),
    "sleepy": ("sleeping",),
    "sleeping": ("sleepy",),
    "tired": ("sleepy", "sad"),
    "charging": ("happy",),
    "thinking": (),
    "talking": (),
}


class CharacterError(Exception):
    """A character pack that cannot be used (the message says why)."""


@dataclass
class SpriteSet:
    """The loaded images of one character."""

    name: str
    images: dict[str, QPixmap] = field(default_factory=dict)

    def pixmap_for(self, mood: Mood, emotion: Emotion) -> QPixmap:
        """The best image for how the pet feels now."""
        key = emotion.value if emotion is not Emotion.NEUTRAL else mood.value
        for candidate in (key, *_FALLBACKS.get(key, ())):
            if candidate in self.images:
                return self.images[candidate]
        return self.images["neutral"]

    def paint(
        self,
        painter: QPainter,
        mood: Mood,
        emotion: Emotion,
        *,
        phase: float,
        blink: bool,
        look: tuple[float, float],
    ) -> None:
        """Draw into the 120 x 120 character space, feet at y = 106."""
        pixmap = self.pixmap_for(mood, emotion)
        if blink and emotion is Emotion.NEUTRAL and "blink" in self.images:
            pixmap = self.images["blink"]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        sleeping = emotion in (Emotion.SLEEPING, Emotion.SLEEPY)
        follow = 0.0 if sleeping else 1.0
        painter.translate(look[0] * 3.0 * follow, look[1] * 1.8 * follow)  # a little parallax
        if mood is Mood.TALKING:  # the whole figure pulses while it speaks
            pulse = 1 + 0.025 * abs(math.sin(phase * 5))
            painter.translate(60, 106)
            painter.scale(1 / pulse, pulse)
            painter.translate(-60, -106)
        box = QRectF(0, 0, CHARACTER, 106)
        scale = min(box.width() / pixmap.width(), box.height() / pixmap.height())
        width, height = pixmap.width() * scale, pixmap.height() * scale
        target = QRectF((CHARACTER - width) / 2, 106 - height, width, height)
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.restore()


def discover(directory: Path) -> dict[str, Path]:
    """Folders under ``directory`` that contain a ``neutral`` image, keyed by folder name."""
    found: dict[str, Path] = {}
    if directory.is_dir():
        for child in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if child.is_dir() and _find_image(child, "neutral") is not None:
                found[child.name] = child
    return found


def load_character(folder: Path) -> SpriteSet:
    """Load a pack. Raises ``CharacterError`` with a readable message when it cannot be used."""
    if not folder.is_dir():
        raise CharacterError(f"character folder not found: {folder}")
    name = folder.name
    meta = folder / "character.yaml"
    if meta.is_file():
        try:
            data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise CharacterError(f"cannot read {meta.name}: {exc}") from exc
        if isinstance(data, dict) and isinstance(data.get("name"), str) and data["name"].strip():
            name = data["name"].strip()
    sprites = SpriteSet(name)
    for expression in EXPRESSIONS:
        path = _find_image(folder, expression)
        if path is None:
            continue
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            raise CharacterError(f"{path.name} is not a readable image")
        if max(pixmap.width(), pixmap.height()) > _MAX_SIDE:
            raise CharacterError(f"{path.name} is larger than {_MAX_SIDE} pixels; please shrink it")
        sprites.images[expression] = pixmap
    if "neutral" not in sprites.images:
        raise CharacterError("a character needs a neutral.png (or .webp / .jpg)")
    return sprites


def _find_image(folder: Path, expression: str) -> Path | None:
    for extension in EXTENSIONS:
        path = folder / f"{expression}{extension}"
        if path.is_file():
            return path
    return None
