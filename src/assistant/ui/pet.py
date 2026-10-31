"""The desktop pet: a small animated, draggable, always-on-top character drawn with QPainter.

No image assets: the character is vector art, so it stays sharp at any DPI and ships in the wheel.
Left click toggles the chat, dragging moves it (position is remembered), right click opens a menu.
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPoint, QPointF, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QMenu, QWidget

from assistant.ui.state import Mood

PET_SIZE = 120
_FRAME_MS = 40
_DRAG_THRESHOLD = 5  # pixels; below this a press-release is a click
_SNAP = 16  # pixels from a screen edge at which the pet sticks to it

_LAMP = {
    Mood.IDLE: QColor("#5be37d"),
    Mood.THINKING: QColor("#ffc247"),
    Mood.TALKING: QColor("#5bc8ff"),
    Mood.ASKING: QColor("#b88cff"),
    Mood.ERROR: QColor("#ff5b5b"),
}
_BODY_TOP, _BODY_BOTTOM, _BODY_EDGE = QColor("#7fa4ff"), QColor("#4a69d8"), QColor("#2f46a0")
_SCREEN, _GLOW = QColor("#0e1633"), QColor("#9ff3ff")


def _round_pen(color: QColor, width: float) -> QPen:
    return QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)


def draw_pet(
    painter: QPainter,
    rect: QRectF,
    mood: Mood,
    *,
    phase: float = 0.0,
    blink: bool = False,
    attention: bool = False,
) -> None:
    """Paint the character into ``rect``. ``phase`` (radians) drives every animation."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = min(rect.width(), rect.height()) / PET_SIZE
    painter.translate(
        rect.center().x() - PET_SIZE * scale / 2, rect.center().y() - PET_SIZE * scale / 2
    )
    painter.scale(scale, scale)

    bob = math.sin(phase) * (4 if mood is Mood.TALKING else 2.5)
    if mood is Mood.ERROR:
        bob = math.sin(phase * 6) * 1.5  # shiver
    painter.setPen(Qt.PenStyle.NoPen)

    painter.setBrush(QColor(0, 0, 0, 40))  # shadow stays on the ground while the body bobs
    painter.drawEllipse(QRectF(26 + bob * 0.3, 104, 68 - bob * 0.6, 8))

    painter.translate(0, bob)
    # antenna
    painter.setPen(_round_pen(_BODY_EDGE, 3))
    painter.drawLine(QPointF(60, 34), QPointF(60, 20))
    lamp = QColor(_LAMP[mood])
    pulse = 0.65 + 0.35 * math.sin(phase * (4 if mood is not Mood.IDLE else 1.5))
    glow = QColor(lamp)
    glow.setAlphaF(0.30 * pulse)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(glow)
    painter.drawEllipse(QPointF(60, 17), 10, 10)
    painter.setBrush(lamp)
    painter.drawEllipse(QPointF(60, 17), 5.5, 5.5)

    # ears and body
    painter.setBrush(_BODY_EDGE)
    painter.drawEllipse(QPointF(15, 68), 8, 11)
    painter.drawEllipse(QPointF(105, 68), 8, 11)
    body = QRectF(20, 33, 80, 70)
    gradient = QLinearGradient(body.topLeft(), body.bottomLeft())
    gradient.setColorAt(0, _BODY_TOP)
    gradient.setColorAt(1, _BODY_BOTTOM)
    painter.setBrush(QBrush(gradient))
    painter.setPen(QPen(_BODY_EDGE, 2.5))
    painter.drawRoundedRect(body, 28, 28)

    # face screen
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_SCREEN)
    painter.drawRoundedRect(QRectF(29, 47, 62, 38), 16, 16)
    _draw_face(painter, mood, phase, blink)
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


def _draw_face(painter: QPainter, mood: Mood, phase: float, blink: bool) -> None:
    glow_pen = _round_pen(_GLOW, 3.2)
    left, right, eye_y = QPointF(46, 62), QPointF(74, 62), 62.0

    if mood is Mood.ERROR:  # x x
        painter.setPen(_round_pen(QColor("#ff8b8b"), 3))
        for cx in (left.x(), right.x()):
            painter.drawLine(QPointF(cx - 4, eye_y - 4), QPointF(cx + 4, eye_y + 4))
            painter.drawLine(QPointF(cx - 4, eye_y + 4), QPointF(cx + 4, eye_y - 4))
        painter.drawArc(QRectF(51, 74, 18, 9), 20 * 16, 140 * 16)  # frown
        return

    look = 0.0
    if mood is Mood.THINKING:
        look = math.sin(phase * 2.2) * 4  # eyes scan side to side
    if blink:
        painter.setPen(glow_pen)
        for p in (left, right):
            painter.drawLine(QPointF(p.x() - 5 + look, p.y()), QPointF(p.x() + 5 + look, p.y()))
    else:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_GLOW)
        height = 15 if mood is Mood.ASKING else 12
        for p in (left, right):
            painter.drawEllipse(QPointF(p.x() + look, p.y()), 5, height / 2)

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(glow_pen)
    if mood is Mood.TALKING:
        open_ = 3 + abs(math.sin(phase * 5)) * 5
        painter.setBrush(_GLOW)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(60, 76), 5, open_ / 1.6)
    elif mood is Mood.ASKING:
        painter.drawEllipse(QPointF(60, 77), 2.2, 2.2)
    elif mood is Mood.THINKING:
        painter.drawLine(QPointF(54, 76), QPointF(66, 76))
    else:
        painter.drawArc(QRectF(51, 68, 18, 10), 200 * 16, 140 * 16)  # smile


def render_icon(mood: Mood = Mood.IDLE, size: int = 64) -> QPixmap:
    """A static portrait, used for the tray icon and window icons."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    draw_pet(painter, QRectF(0, 0, size, size), mood)
    painter.end()
    return pixmap


class PetWidget(QWidget):
    """Frameless, transparent, always-on-top window holding the character."""

    clicked = Signal()
    moved = Signal()

    def __init__(self, settings: QSettings) -> None:
        super().__init__()
        self._settings = settings
        self._mood = Mood.IDLE
        self._attention = False
        self._phase = 0.0
        self._blink_left = 0
        self._next_blink = 60
        self._menu: QMenu | None = None
        self._press_global: QPoint | None = None
        self._press_origin = QPoint()
        self._dragging = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # no taskbar button; the tray icon is the handle
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(PET_SIZE, PET_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to chat · drag to move · right-click for options")

        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._tick)

        self._restore_position()

    # -- public ------------------------------------------------------------------------------

    @property
    def mood(self) -> Mood:
        return self._mood

    def set_mood(self, mood: Mood) -> None:
        self._mood = mood
        self.update()

    def set_attention(self, on: bool) -> None:
        if on != self._attention:
            self._attention = on
            self.update()

    def set_menu(self, menu: QMenu) -> None:
        self._menu = menu

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        self._timer.stop()  # no animation work while hidden
        super().hideEvent(event)

    # -- painting ----------------------------------------------------------------------------

    def _tick(self) -> None:
        self._phase += 0.11
        if self._blink_left:
            self._blink_left -= 1
        else:
            self._next_blink -= 1
            if self._next_blink <= 0:
                self._blink_left = 4
                self._next_blink = random.randint(60, 140)  # noqa: S311  (animation timing only)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        draw_pet(
            painter,
            QRectF(self.rect()),
            self._mood,
            phase=self._phase,
            blink=self._blink_left > 0,
            attention=self._attention,
        )

    # -- mouse: click vs drag ----------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_origin = self.pos()
            self._dragging = False
        elif event.button() == Qt.MouseButton.RightButton and self._menu is not None:
            self._menu.exec(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_global is None:
            return
        delta = event.globalPosition().toPoint() - self._press_global
        if not self._dragging and delta.manhattanLength() < _DRAG_THRESHOLD:
            return
        self._dragging = True
        self.move(self._press_origin + delta)
        self.moved.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._press_global is None:
            return
        was_drag, self._press_global = self._dragging, None
        self._dragging = False
        if was_drag:
            self._snap_to_edges()
            self._settings.setValue("pet/pos", self.pos())
            self.moved.emit()
        else:
            self.clicked.emit()

    # -- placement ---------------------------------------------------------------------------

    def _screen_area(self) -> QRectF:
        screen = self.screen() or QGuiApplication.primaryScreen()
        return QRectF(screen.availableGeometry())

    def _restore_position(self) -> None:
        area = self._screen_area()
        default = QPoint(int(area.right() - PET_SIZE - 24), int(area.bottom() - PET_SIZE - 12))
        saved = self._settings.value("pet/pos", default)
        self.move(self._clamped(saved if isinstance(saved, QPoint) else default))

    def _clamped(self, point: QPoint) -> QPoint:
        screens = QGuiApplication.screens()
        for screen in screens:  # keep a saved spot if it is still on some screen
            if screen.availableGeometry().contains(point + QPoint(PET_SIZE // 2, PET_SIZE // 2)):
                return point
        area = self._screen_area()
        return QPoint(
            int(min(max(point.x(), area.left()), area.right() - PET_SIZE)),
            int(min(max(point.y(), area.top()), area.bottom() - PET_SIZE)),
        )

    def _snap_to_edges(self) -> None:
        area = self._screen_area()
        x, y = self.x(), self.y()
        if abs(x - area.left()) < _SNAP:
            x = int(area.left())
        elif abs(area.right() - (x + PET_SIZE)) < _SNAP:
            x = int(area.right() - PET_SIZE)
        if abs(y - area.top()) < _SNAP:
            y = int(area.top())
        elif abs(area.bottom() - (y + PET_SIZE)) < _SNAP:
            y = int(area.bottom() - PET_SIZE)
        self.move(x, y)
