"""The desktop pet: an animated, draggable, always-on-top character drawn with QPainter.

The built-in characters are vector art (see ``vector_characters``) and your own artwork can replace
them (see ``characters``). Either way the pet behaves the same:

  * Its eyes (and head) follow the mouse pointer anywhere on screen.
  * Hover: it notices you. Keep the pointer on it for a few seconds and it falls in love.
  * Click: it hops and opens the chat. Double-click: it is delighted.
  * Drag: it is surprised while carried, happy when put down, and dizzy if shaken.
  * Leave it alone and it gets sleepy, then falls asleep; any attention wakes it.
Right click opens the menu.

Smoothness: everything is timed in seconds (not frames), expressions cross-fade, blinks close the
eyelids gradually and the mood light eases between colours.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QMenu, QWidget

from assistant.ui.characters import EXPRESSIONS, SpriteSet
from assistant.ui.state import MOOD_EMOTION, Emotion, Mood
from assistant.ui.vector_characters import (
    LAMP,
    ROBOT,
    VectorCharacter,
    heart_path,
    sparkle_path,
)

CHARACTER = 120  # the character is drawn in a 120 x 120 space...
MARGIN_X, MARGIN_TOP = 15, 24  # ...with room around it for hearts, "z"s and sparkles
CANVAS = CHARACTER + 2 * MARGIN_X  # 150: the window is a square of this size
PET_SIZE = CANVAS  # the drawing space; the window itself can be any of PET_SIZES

PET_SIZES: dict[str, int] = {
    "Tiny": 70,
    "Small": 95,
    "Medium": 120,
    "Large": 150,
    "Extra large": 200,
}
DEFAULT_SIZE = "Small"

_FPS = 40
_FRAME_MS = 1000 // _FPS
_STEP = 25 / _FPS  # the physics constants below were tuned at 25 frames per second
_DRAG_THRESHOLD = 5  # pixels; below this a press-release is a click
_SNAP = 16  # pixels from a screen edge at which the pet sticks to it
_LOOK_RANGE = 700  # beyond this distance (px) the pet stops following the pointer
_HOVER_RADIUS = 0.42  # share of the window size that counts as "on the pet"
_PET_SECONDS = 3.0  # hover this long and it falls in love
_SLEEPY_AFTER, _ASLEEP_AFTER = 75.0, 110.0  # seconds without any attention
_FADE_SECONDS = 0.22  # cross-fade between expressions
_BLINK_SECONDS = 0.2

_PINK = QColor("#ff8fb3")
_GOLD = QColor("#ffe27a")
_WARM = QColor("#ffd27a")


@dataclass(frozen=True, slots=True)
class FadeFrom:
    """The expression being faded out while a new one fades in."""

    emotion: Emotion
    mood: Mood
    age: float


def _round_pen(color: QColor, width: float) -> QPen:
    return QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)


def _resolve(emotion: Emotion, mood: Mood) -> Emotion:
    """The expression to show: an explicit emotion wins, otherwise the mood may imply one."""
    return emotion if emotion is not Emotion.NEUTRAL else MOOD_EMOTION.get(mood, Emotion.NEUTRAL)


def draw_pet(
    painter: QPainter,
    rect: QRectF,
    mood: Mood,
    *,
    phase: float = 0.0,
    blink: float = 0.0,
    attention: bool = False,
    emotion: Emotion = Emotion.NEUTRAL,
    age: float = 0.0,
    look: tuple[float, float] = (0.0, 0.0),
    squash: float = 0.0,
    lift: float = 0.0,
    tilt: float = 0.0,
    margin: bool = True,
    sprites: SpriteSet | None = None,
    vector: VectorCharacter = ROBOT,
    effects: bool = True,
    lamp: QColor | None = None,
    fade_from: FadeFrom | None = None,
    fade: float = 1.0,
) -> None:
    """Paint the character into ``rect``.

    ``phase`` (radians) drives the idle animation, ``blink`` is how closed the eyes are (0..1),
    ``age`` how long the current emotion has lasted, ``look`` where the eyes point (-1..1 on each
    axis), ``squash`` stretches the body (positive) or flattens it (negative) and ``lift`` raises it
    off the ground. While ``fade`` < 1 the expression described by ``fade_from`` fades out.
    """
    emotion_now = _resolve(emotion, mood)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    canvas = CANVAS if margin else CHARACTER
    scale = min(rect.width(), rect.height()) / canvas
    painter.translate(
        rect.center().x() - canvas * scale / 2, rect.center().y() - canvas * scale / 2
    )
    painter.scale(scale, scale)
    if margin:
        painter.translate(MARGIN_X, MARGIN_TOP)

    sleeping = emotion_now in (Emotion.SLEEPING, Emotion.SLEEPY)
    bob_amp = 1.2 if sleeping else (4 if mood is Mood.TALKING else 2.5)
    bob = math.sin(phase * (0.5 if sleeping else 1.0)) * bob_amp
    if emotion_now is Emotion.DIZZY:
        bob = math.sin(phase * 5) * 2
    breath = math.sin(phase * (0.5 if sleeping else 0.9)) * (0.022 if sleeping else 0.012)
    painter.setPen(Qt.PenStyle.NoPen)

    shadow = max(0.4, 1 - lift / 40)
    painter.setBrush(QColor(0, 0, 0, int(40 * shadow)))  # the shadow stays on the ground
    painter.drawEllipse(
        QRectF(26 + bob * 0.3 + (1 - shadow) * 10, 104, (68 - bob * 0.6) * shadow, 8)
    )

    painter.translate(60, 104)  # pivot at the feet
    painter.rotate(tilt)
    total = squash + breath
    painter.scale(1 - total * 0.5, 1 + total)
    painter.translate(-60, -104 + bob - lift)

    if sprites is None:
        vector.paint_body(painter, lamp or LAMP[mood], phase, mood is not Mood.IDLE)

    def expression(show_emotion: Emotion, show_mood: Mood, show_age: float, opacity: float) -> None:
        if opacity <= 0.01:
            return
        painter.setOpacity(opacity)
        if sprites is None:
            painter.save()
            fx, fy = vector.face_center
            painter.translate(fx, fy)
            painter.scale(vector.face_scale, vector.face_scale)
            painter.translate(-60, -68)
            _draw_face(painter, show_mood, show_emotion, phase, blink, show_age, look, vector)
            painter.restore()
        else:
            sprites.paint(
                painter, show_mood, show_emotion, phase=phase, blink=blink > 0.5, look=look
            )
        if effects:
            _draw_effects(painter, show_emotion, show_age, phase)
        painter.setOpacity(1.0)

    if fade_from is not None and fade < 1.0:
        expression(
            _resolve(fade_from.emotion, fade_from.mood), fade_from.mood, fade_from.age, 1 - fade
        )
    expression(emotion_now, mood, age, fade if fade_from is not None else 1.0)
    painter.restore()

    if attention:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        badge = QRectF(rect.right() - 30 * scale, rect.top() + 4 * scale, 22 * scale, 22 * scale)
        painter.setPen(QPen(QColor("white"), 2 * scale))
        painter.setBrush(QColor("#ff4d4d"))
        painter.drawEllipse(badge)
        painter.setPen(QColor("white"))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(max(8, int(14 * scale)))
        painter.setFont(font)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "!")
        painter.restore()


def _eye_points(look: tuple[float, float], emotion: Emotion) -> tuple[QPointF, QPointF]:
    follow = 0.0 if emotion in (Emotion.SLEEPING, Emotion.DIZZY, Emotion.LOVE) else 1.0
    if emotion is Emotion.SLEEPY:
        follow = 0.3
    elif emotion is Emotion.TIRED:
        follow = 0.4
    dx, dy = look[0] * 4.0 * follow, look[1] * 2.8 * follow
    return QPointF(46 + dx, 62 + dy), QPointF(74 + dx, 62 + dy)


def _draw_face(
    painter: QPainter,
    mood: Mood,
    emotion: Emotion,
    phase: float,
    blink: float,
    age: float,
    look: tuple[float, float],
    vector: VectorCharacter,
) -> None:
    """Eyes, brows and mouth, in the robot's face space (the caller moves and scales it)."""
    ink, paper = vector.ink, vector.paper
    pen = _round_pen(ink, 3.2)
    left, right = _eye_points(look, emotion)
    mouth = vector.mouth
    painter.setBrush(Qt.BrushStyle.NoBrush)

    def shine(p: QPointF, rx: float, ry: float) -> None:
        if vector.shine:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 235))
            painter.drawEllipse(QPointF(p.x() + rx * 0.32, p.y() - ry * 0.38), rx * 0.3, rx * 0.3)

    if emotion is Emotion.TIRED:  # heavy lids, bags under the eyes, a yawn now and then
        bags = QColor("#8a7fd1")
        bags.setAlpha(150)
        for p in (left, right):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ink)
            painter.drawChord(QRectF(p.x() - 5, p.y() - 4, 10, 10), 180 * 16, 180 * 16)
            painter.setPen(pen)
            painter.drawLine(QPointF(p.x() - 6, p.y() + 1), QPointF(p.x() + 6, p.y() + 1))
            painter.setPen(_round_pen(bags, 1.6))
            painter.drawArc(QRectF(p.x() - 5, p.y() + 6, 10, 5), 200 * 16, 140 * 16)
        if mouth:
            yawn = max(0.0, math.sin(phase * 0.35)) ** 10
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if yawn > 0.1:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(ink)
                painter.drawEllipse(QPointF(60, 77), 3.6 + yawn * 1.5, 2 + yawn * 5)
            else:
                painter.setPen(pen)
                painter.drawArc(QRectF(52, 76, 16, 6), 20 * 16, 140 * 16)
        return
    if emotion is Emotion.CHARGING:  # bright, wide-awake eyes and a grin
        painter.setPen(Qt.PenStyle.NoPen)
        for p in (left, right):
            painter.setBrush(ink)
            painter.drawEllipse(p, 5.4, 6.6)
            shine(p, 5.4, 6.6)
        if mouth:
            painter.setBrush(ink)
            painter.drawChord(QRectF(51, 69, 18, 13), 180 * 16, 180 * 16)
        return
    if emotion is Emotion.HAPPY:  # ^ ^ and an open smile
        painter.setPen(pen)
        for p in (left, right):
            painter.drawArc(QRectF(p.x() - 5, p.y() - 3, 10, 10), 20 * 16, 140 * 16)
        if mouth:
            painter.setBrush(ink)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawChord(QRectF(51, 69, 18, 13), 180 * 16, 180 * 16)
        _blush(painter)
        return
    if emotion is Emotion.LOVE:
        painter.setPen(Qt.PenStyle.NoPen)
        beat = 1 + 0.12 * math.sin(age * 0.5)
        painter.setBrush(_PINK)
        for p in (left, right):
            painter.save()
            painter.translate(p.x(), p.y() - 1)
            painter.scale(beat, beat)
            painter.drawPath(heart_path(4.4))
            painter.restore()
        if mouth:
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(51, 68, 18, 10), 200 * 16, 140 * 16)
        _blush(painter)
        return
    if emotion is Emotion.SURPRISED:
        painter.setPen(Qt.PenStyle.NoPen)
        for p in (left, right):
            painter.setBrush(ink)
            painter.drawEllipse(p, 6.5, 7.5)
            painter.setBrush(paper)
            painter.drawEllipse(QPointF(p.x() + look[0] * 1.8, p.y() + look[1] * 1.8), 2.4, 2.4)
        if mouth:
            painter.setBrush(ink)
            painter.drawEllipse(QPointF(60, 77), 3.6, 4.6)
        return
    if emotion is Emotion.SAD:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        droop = 1 - 0.85 * blink
        for p in (left, right):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ink)  # shine() changes the brush, so set it for every eye
            painter.drawEllipse(QPointF(p.x(), p.y() + 2), 4.4, 5 * max(droop, 0.12))
            shine(QPointF(p.x(), p.y() + 2), 4.4, 5)
        painter.setPen(_round_pen(ink, 2.4))  # worried brows
        painter.drawLine(QPointF(left.x() - 6, left.y() - 8), QPointF(left.x() + 4, left.y() - 11))
        painter.drawLine(
            QPointF(right.x() + 6, right.y() - 8), QPointF(right.x() - 4, right.y() - 11)
        )
        if mouth:
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(52, 77, 16, 8), 20 * 16, 140 * 16)
        return
    if emotion is Emotion.DIZZY:
        painter.setPen(_round_pen(_WARM if vector.ink.lightness() > 120 else ink, 2))
        spin = int(age * 40 * 16)
        for p in (left, right):
            painter.drawArc(QRectF(p.x() - 6, p.y() - 6, 12, 12), spin, 270 * 16)
            painter.drawArc(QRectF(p.x() - 3, p.y() - 3, 6, 6), -spin, 270 * 16)
        if mouth:
            painter.setPen(pen)
            painter.drawLine(QPointF(53, 77), QPointF(67, 77))
        return
    if emotion is Emotion.SLEEPING:
        painter.setPen(pen)
        for p in (left, right):
            painter.drawArc(QRectF(p.x() - 5, p.y() - 4, 10, 8), 200 * 16, 140 * 16)
        if mouth:
            breathe = 2.2 + 1.2 * math.sin(phase * 0.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ink)
            painter.drawEllipse(QPointF(60, 77), 2.6, breathe)
        return
    if emotion is Emotion.SLEEPY:
        painter.setPen(pen)
        for p in (left, right):
            painter.drawLine(QPointF(p.x() - 5, p.y() + 1), QPointF(p.x() + 5, p.y() + 1))
        if mouth:
            painter.drawLine(QPointF(55, 77), QPointF(65, 77))
        return

    # No transient emotion: the face follows the mood.
    thinking = mood is Mood.THINKING
    if thinking:  # eyes scan side to side while working, ignoring the pointer
        scan = math.sin(phase * 2.2) * 4
        left, right = QPointF(46 + scan, 62), QPointF(74 + scan, 62)
    curious = emotion is Emotion.CURIOUS
    openness = 1 - blink  # eyelids close gradually
    for index, p in enumerate((left, right)):
        tall = (15 if curious and index == 1 else 12) / 2
        if openness < 0.16:
            painter.setPen(pen)
            painter.drawLine(QPointF(p.x() - 5, p.y()), QPointF(p.x() + 5, p.y()))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ink)
            painter.drawEllipse(p, 5, tall * openness)
            if openness > 0.6:
                shine(p, 5, tall)

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(pen)
    if not mouth:
        return
    if mood is Mood.TALKING:
        open_ = 3 + abs(math.sin(phase * 5)) * 5
        painter.setBrush(ink)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(60, 76), 5, open_ / 1.6)
    elif curious:
        painter.drawEllipse(QPointF(60, 77), 2.2, 2.2)
    elif thinking:
        painter.drawLine(QPointF(54, 76), QPointF(66, 76))
    else:
        painter.drawArc(QRectF(51, 68, 18, 10), 200 * 16, 140 * 16)  # smile


def _blush(painter: QPainter) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 143, 179, 110))
    painter.drawEllipse(QPointF(37, 74), 5, 3)
    painter.drawEllipse(QPointF(83, 74), 5, 3)


def _bolt_path(size: float) -> QPainterPath:
    path = QPainterPath()
    for i, (x, y) in enumerate(
        ((0.3, -1.0), (-0.7, 0.15), (-0.05, 0.15), (-0.3, 1.0), (0.7, -0.2), (0.05, -0.2))
    ):
        point = QPointF(x * size, y * size)
        path.moveTo(point) if i == 0 else path.lineTo(point)
    path.closeSubpath()
    return path


def _draw_low_battery(painter: QPainter, age: float) -> None:
    """A little battery above the head with one red bar that pulses."""
    pulse = 0.7 + 0.3 * math.sin(age * 0.35)
    painter.save()
    painter.setPen(_round_pen(QColor("#8b97a8"), 1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(46, 1, 24, 11), 2.5, 2.5)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#8b97a8"))
    painter.drawRect(QRectF(70.5, 4, 2.2, 5))
    red = QColor("#f31260")
    red.setAlphaF(pulse)
    painter.setBrush(red)
    painter.drawRoundedRect(QRectF(48, 3, 5, 7), 1, 1)
    painter.restore()


def _draw_effects(painter: QPainter, emotion: Emotion, age: float, phase: float) -> None:
    """Things floating around the character (hearts, sparkles, "z", "?" ...)."""
    painter.setPen(Qt.PenStyle.NoPen)
    if emotion is Emotion.LOVE:
        for i in range(3):
            t = ((age * 0.045) + i / 3) % 1.0
            x = 60 + (i - 1) * 24 + math.sin(t * 6 + i) * 5
            y = 22 - t * 34
            color = QColor(_PINK)
            color.setAlphaF(1 - t)
            painter.setBrush(color)
            painter.save()
            painter.translate(x, y)
            painter.drawPath(heart_path(4.5 + (1 - t) * 2))
            painter.restore()
    elif emotion is Emotion.HAPPY:
        for i, (x, y) in enumerate(((20, 22), (100, 18), (104, 52))):
            twinkle = 0.5 + 0.5 * math.sin(age * 0.6 + i * 2)
            color = QColor(_GOLD)
            color.setAlphaF(0.3 + 0.7 * twinkle)
            painter.setBrush(color)
            painter.save()
            painter.translate(x, y)
            painter.drawPath(sparkle_path(3.5 + 3 * twinkle))
            painter.restore()
    elif emotion in (Emotion.SLEEPING, Emotion.SLEEPY):
        font = painter.font()
        font.setBold(True)
        for i in range(3):
            t = ((phase * 0.1) + i / 3) % 1.0
            color = QColor("#cfe3ff")
            color.setAlphaF((1 - t) * min(1.0, t * 6))
            painter.setPen(color)
            font.setPixelSize(int(8 + 8 * t))
            painter.setFont(font)
            painter.drawText(QPointF(86 + t * 14, 30 - t * 24), "z")
    elif emotion is Emotion.TIRED:
        t = (age * 0.03) % 1.0  # a sweat drop slides down
        drop = QColor("#8fd3ff")
        drop.setAlphaF(1 - t * 0.7)
        painter.setBrush(drop)
        painter.drawEllipse(QPointF(90, 34 + t * 16), 2.4, 3.4)
        _draw_low_battery(painter, age)
    elif emotion is Emotion.CHARGING:
        for i in range(3):
            t = ((age * 0.04) + i / 3) % 1.0
            x = (12, 108, 100)[i] + math.sin(t * 7 + i) * 3  # up the sides, clear of the face
            y = 84 - t * 62
            color = QColor("#ffd23f")
            color.setAlphaF(min(1.0, (1 - t) * 2))
            painter.setBrush(color)
            painter.save()
            painter.translate(x, y)
            painter.drawPath(_bolt_path(5 + 2 * (1 - t)))
            painter.restore()
    elif emotion is Emotion.CURIOUS:
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(20)
        painter.setFont(font)
        painter.setPen(QColor("#d9c2ff"))
        painter.drawText(QPointF(92, 24 + math.sin(phase * 2) * 2), "?")
    elif emotion is Emotion.SURPRISED:
        painter.setPen(_round_pen(QColor("#ffe27a"), 2.4))
        for dx in (-14, 0, 14):
            top = QPointF(60 + dx * 1.7, -6 - abs(dx) * 0.25)
            painter.drawLine(QPointF(60 + dx * 1.2, 4 - abs(dx) * 0.2), top)
    elif emotion is Emotion.SAD:
        t = (age * 0.05) % 1.0  # a tear running down
        color = QColor("#8fd3ff")
        color.setAlphaF(1 - t * 0.6)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(40, 68 + t * 14), 2.2, 3.2)
    elif emotion is Emotion.DIZZY:
        for i in range(3):
            angle = age * 0.35 + i * 2.1
            painter.setBrush(_GOLD)
            painter.drawEllipse(
                QPointF(60 + math.cos(angle) * 22, 14 + math.sin(angle) * 5), 2.6, 2.6
            )


def write_example_character(folder: Path, vector: VectorCharacter = ROBOT) -> list[str]:
    """Write a built-in character as an image pack: a template with every expected file name.

    Replace the images with your own artwork (same names, transparent background) to get started.
    """
    folder.mkdir(parents=True, exist_ok=True)
    emotions = {e.value for e in Emotion}
    moods = {m.value for m in Mood}
    written = []
    for name in EXPRESSIONS:
        size = 256
        image = QPixmap(size, size)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        draw_pet(
            painter,
            QRectF(0, 0, size, size),
            Mood(name) if name in moods else Mood.IDLE,
            emotion=Emotion(name) if name in emotions else Emotion.NEUTRAL,
            margin=False,
            blink=1.0 if name == "blink" else 0.0,
            effects=False,  # hearts, "z"s and sparkles are drawn by the pet itself
            vector=vector,
        )
        painter.end()
        image.save(str(folder / f"{name}.png"))
        written.append(f"{name}.png")
    (folder / "character.yaml").write_text(f"name: Example {vector.name}\n", encoding="utf-8")
    return written


def render_icon(
    mood: Mood = Mood.IDLE,
    size: int = 64,
    sprites: SpriteSet | None = None,
    vector: VectorCharacter = ROBOT,
) -> QPixmap:
    """A static portrait, used for the tray icon, window icons and previews."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    draw_pet(painter, QRectF(0, 0, size, size), mood, margin=False, sprites=sprites, vector=vector)
    painter.end()
    return pixmap


def _smooth(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


class PetWidget(QWidget):
    """Frameless, transparent, always-on-top window holding the character."""

    clicked = Signal()
    moved = Signal()

    def __init__(
        self,
        settings: QSettings,
        sprites: SpriteSet | None = None,
        vector: VectorCharacter = ROBOT,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._sprites = sprites
        self._vector = vector
        self._mood = Mood.IDLE
        self._attention = False
        self._phase = 0.0
        self._blink_left = 0.0  # seconds of the current blink still to run
        self._next_blink = 2.0  # seconds until the next one
        self._menu: QMenu | None = None
        self._press_global: QPoint | None = None
        self._press_origin = QPoint()
        self._dragging = False

        # expression state
        self._override = Emotion.NEUTRAL
        self._override_frames = 0
        self._effective = Emotion.NEUTRAL
        self._face_key: tuple[Emotion, Mood | None] = (Emotion.NEUTRAL, Mood.IDLE)
        self._age = 0.0
        self._fade_from: FadeFrom | None = None
        self._fade = 1.0
        self._idle_frames = 0
        self._tired = False
        self._hover_frames = 0
        self._was_hovering = False
        self._look = (0.0, 0.0)
        self._lamp = QColor(LAMP[Mood.IDLE])
        # tiny physics for hops and squash
        self._lift, self._lift_v = 0.0, 0.0
        self._squash, self._squash_v = 0.0, 0.0
        # shake detection while dragging
        self._last_x = 0
        self._last_dir = 0
        self._reversals: list[float] = []

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # no taskbar button; the tray icon is the handle
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._size = self._saved_size()
        self.setFixedSize(self._size, self._size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to chat · drag to move · right-click for options")

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._tick)

        self._restore_position()

    # -- public ------------------------------------------------------------------------------

    @property
    def mood(self) -> Mood:
        return self._mood

    @property
    def emotion(self) -> Emotion:
        """The expression currently shown (NEUTRAL means the face follows the mood)."""
        return self._effective

    def set_mood(self, mood: Mood) -> None:
        if mood is not Mood.IDLE:
            self._idle_frames = 0
        self._mood = mood
        self.update()

    def set_attention(self, on: bool) -> None:
        if on != self._attention:
            self._attention = on
            self.update()

    def set_menu(self, menu: QMenu) -> None:
        self._menu = menu

    def set_character(
        self, sprites: SpriteSet | None, vector: VectorCharacter | None = None
    ) -> None:
        """Switch to image artwork or a built-in character, and say hello in it."""
        self._sprites = sprites
        self._vector = vector or ROBOT
        self.react(Emotion.HAPPY, 1.5)
        self.hop(0.8)
        self.update()

    def react(self, emotion: Emotion, seconds: float = 2.0) -> None:
        """Show ``emotion`` for ``seconds`` (also counts as attention: it wakes the pet up)."""
        self._idle_frames = 0
        self._override = emotion
        self._override_frames = max(1, int(seconds * _FPS))

    def hop(self, strength: float = 1.0) -> None:
        self._lift_v = 8.5 * strength

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self._timer.stop()  # no animation work while hidden
        super().hideEvent(event)

    # -- animation ---------------------------------------------------------------------------

    def _tick(self) -> None:
        self._phase += (0.07 if self._effective is Emotion.TIRED else 0.11) * _STEP
        self._blinking()
        self._follow_pointer()
        self._hover()
        self._physics()
        self._update_emotion()
        self._ease_lamp()
        self.update()

    def _blinking(self) -> None:
        dt = 1 / _FPS
        if self._blink_left > 0:
            self._blink_left = max(0.0, self._blink_left - dt)
            return
        self._next_blink -= dt
        if self._next_blink <= 0:
            self._blink_left = _BLINK_SECONDS
            self._next_blink = random.uniform(2.0, 5.2)  # noqa: S311  (animation timing only)

    def _blink_amount(self) -> float:
        """0 = open, 1 = shut: a smooth close and re-open over the length of a blink."""
        if self._blink_left <= 0 or self._effective in (Emotion.SLEEPING, Emotion.SLEEPY):
            return 0.0
        progress = 1 - self._blink_left / _BLINK_SECONDS
        return math.sin(math.pi * progress)

    def _centre(self) -> QPoint:
        return self.mapToGlobal(self.rect().center())

    def _follow_pointer(self) -> None:
        offset = QCursor.pos() - self._centre()
        distance = math.hypot(offset.x(), offset.y())
        if distance > _LOOK_RANGE:
            target = (0.0, 0.0)
        else:
            target = (max(-1.0, min(1.0, offset.x() / 160)), max(-1.0, min(1.0, offset.y() / 160)))
        k = 1 - (1 - 0.28) ** _STEP  # the same easing at any frame rate
        self._look = (
            self._look[0] + (target[0] - self._look[0]) * k,
            self._look[1] + (target[1] - self._look[1]) * k,
        )

    def _hover(self) -> None:
        offset = QCursor.pos() - self._centre()
        hovering = math.hypot(offset.x(), offset.y()) < self._size * _HOVER_RADIUS
        if hovering and not self._dragging:
            self._idle_frames = 0
            self._hover_frames += 1
            if not self._was_hovering:
                self._on_pointer_arrived()
            if self._hover_frames == int(_PET_SECONDS * _FPS):
                self.react(Emotion.LOVE, 4.0)
        else:
            self._hover_frames = 0
        self._was_hovering = hovering and not self._dragging

    def _on_pointer_arrived(self) -> None:
        asleep = self._effective in (Emotion.SLEEPING, Emotion.SLEEPY)
        self.react(Emotion.SURPRISED, 0.8)
        self.hop(0.55 if asleep else 0.35)

    def _physics(self) -> None:
        s = _STEP
        if self._lift > 0 or self._lift_v > 0:  # a hop under gravity
            self._lift += self._lift_v * s
            self._lift_v -= 1.1 * s
            if self._lift <= 0:
                self._lift = 0.0
                if self._lift_v < -2:
                    self._squash_v = -0.05 * abs(self._lift_v)  # land with a squish
                self._lift_v = 0.0
        # a damped spring pulls the squash back to zero
        self._squash_v += (-0.35 * self._squash - 0.18 * self._squash_v) * s
        self._squash += self._squash_v * s
        if self._lift > 0:
            self._squash = max(
                self._squash, min(0.12, self._lift_v * 0.012)
            )  # stretch while rising

    def _update_emotion(self) -> None:
        self._idle_frames += 1
        if self._override_frames > 0:
            self._override_frames -= 1
            effective = self._override
        elif self._mood is Mood.IDLE and self._idle_frames > _ASLEEP_AFTER * _FPS:
            effective = Emotion.SLEEPING
        elif self._mood is Mood.IDLE and self._tired:
            effective = Emotion.TIRED
        elif self._mood is Mood.IDLE and self._idle_frames > _SLEEPY_AFTER * _FPS:
            effective = Emotion.SLEEPY
        else:
            effective = Emotion.NEUTRAL

        shown = _resolve(effective, self._mood)
        key = (shown, self._mood if shown is Emotion.NEUTRAL else None)
        if key != self._face_key:  # start cross-fading from what was on screen
            self._fade_from = FadeFrom(
                self._face_key[0], self._face_key[1] or self._mood, self._age
            )
            self._fade = 0.0
            self._face_key = key
            self._age = 0.0
        else:
            self._age += _STEP
        if self._fade < 1.0:
            self._fade = min(1.0, self._fade + 1 / (_FADE_SECONDS * _FPS))
        self._effective = effective

    def _ease_lamp(self) -> None:
        """The mood light glides to its new colour instead of jumping."""
        target = LAMP[self._mood]
        k = 1 - (1 - 0.18) ** _STEP
        # float channels: rounding to whole numbers each frame would stall a few shades short
        self._lamp = QColor.fromRgbF(
            self._lamp.redF() + (target.redF() - self._lamp.redF()) * k,
            self._lamp.greenF() + (target.greenF() - self._lamp.greenF()) * k,
            self._lamp.blueF() + (target.blueF() - self._lamp.blueF()) * k,
        )

    # -- painting ----------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        sleeping = self._effective in (Emotion.SLEEPING, Emotion.SLEEPY)
        draw_pet(
            painter,
            QRectF(self.rect()),
            self._mood,
            phase=self._phase,
            blink=self._blink_amount(),
            attention=self._attention,
            emotion=self._effective,
            age=self._age,
            look=self._look,
            squash=self._squash,
            lift=self._lift,
            tilt=self._look[0] * 3.5 if not sleeping else 0.0,
            sprites=self._sprites,
            vector=self._vector,
            lamp=self._lamp,
            fade_from=self._fade_from,
            fade=_smooth(self._fade),
        )

    # -- mouse: click vs drag ----------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._idle_frames = 0
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_origin = self.pos()
            self._dragging = False
            self._last_x = self._press_global.x()
            self._last_dir = 0
            self._reversals.clear()
        elif event.button() == Qt.MouseButton.RightButton and self._menu is not None:
            self._menu.exec(event.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.react(Emotion.LOVE, 3.0)
            self.hop(1.3)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_global is None:
            return
        position = event.globalPosition().toPoint()
        delta = position - self._press_global
        if not self._dragging and delta.manhattanLength() < _DRAG_THRESHOLD:
            return
        if not self._dragging:
            self._dragging = True
            self.react(Emotion.SURPRISED, 60.0)  # held until it is put down
        self._detect_shake(position.x())
        self.move(self._press_origin + delta)
        self.moved.emit()

    def _detect_shake(self, x: int) -> None:
        step = x - self._last_x
        if abs(step) < 7:
            return
        direction = 1 if step > 0 else -1
        if self._last_dir and direction != self._last_dir:
            now = time.monotonic()
            self._reversals = [t for t in self._reversals if now - t < 1.0] + [now]
            if len(self._reversals) >= 5:
                self._reversals.clear()
                self.react(Emotion.DIZZY, 3.0)
        self._last_dir, self._last_x = direction, x

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._press_global is None:
            return
        was_drag, self._press_global = self._dragging, None
        self._dragging = False
        if was_drag:
            self._snap_to_edges()
            self._settings.setValue("pet/pos", self.pos())
            if self._effective is not Emotion.DIZZY:
                self.react(Emotion.HAPPY, 1.4)
            self.hop(0.6)
            self.moved.emit()
        else:
            self.react(Emotion.HAPPY, 1.5)
            self.hop(1.0)
            self.clicked.emit()

    # -- placement ---------------------------------------------------------------------------

    def _screen_area(self) -> QRectF:
        screen = self.screen() or QGuiApplication.primaryScreen()
        return QRectF(screen.availableGeometry())

    def _saved_size(self) -> int:
        raw: object = self._settings.value("pet/size", PET_SIZES[DEFAULT_SIZE])
        try:
            value = int(str(raw))
        except ValueError:
            value = PET_SIZES[DEFAULT_SIZE]
        return max(min(PET_SIZES.values()), min(max(PET_SIZES.values()), value))

    def set_tired(self, tired: bool) -> None:
        """Low battery: look tired while idle (it never gets in the way of a reply)."""
        self._tired = tired

    @property
    def size_px(self) -> int:
        return self._size

    def set_size(self, pixels: int) -> None:
        """Resize in place (the centre stays put), keep it on screen, and remember it."""
        pixels = max(min(PET_SIZES.values()), min(max(PET_SIZES.values()), int(pixels)))
        self._settings.setValue("pet/size", pixels)
        if pixels == self._size:
            return
        centre = self.geometry().center()
        self._size = pixels
        self.setFixedSize(pixels, pixels)
        self.move(self._clamped(QPoint(centre.x() - pixels // 2, centre.y() - pixels // 2)))
        self.moved.emit()
        self.update()

    def _restore_position(self) -> None:
        area = self._screen_area()
        default = QPoint(int(area.right() - self._size - 24), int(area.bottom() - self._size - 12))
        saved = self._settings.value("pet/pos", default)
        self.move(self._clamped(saved if isinstance(saved, QPoint) else default))

    def _clamped(self, point: QPoint) -> QPoint:
        screens = QGuiApplication.screens()
        for screen in screens:  # keep a saved spot if it is still on some screen
            if screen.availableGeometry().contains(
                point + QPoint(self._size // 2, self._size // 2)
            ):
                return point
        area = self._screen_area()
        return QPoint(
            int(min(max(point.x(), area.left()), area.right() - self._size)),
            int(min(max(point.y(), area.top()), area.bottom() - self._size)),
        )

    def _snap_to_edges(self) -> None:
        area = self._screen_area()
        x, y = self.x(), self.y()
        if abs(x - area.left()) < _SNAP:
            x = int(area.left())
        elif abs(area.right() - (x + self._size)) < _SNAP:
            x = int(area.right() - self._size)
        if abs(y - area.top()) < _SNAP:
            y = int(area.top())
        elif abs(area.bottom() - (y + self._size)) < _SNAP:
            y = int(area.bottom() - self._size)
        self.move(x, y)
