"""A small speech bubble next to the pet for short notices (battery, replies while chat is closed)."""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

_MAX_WIDTH = 260
_PAD_X, _PAD_Y, _TAIL, _GAP = 14, 10, 9, 4
_SECONDS_BASE, _SECONDS_PER_CHAR = 3.5, 0.05
_QUEUE_MAX = 4

_ACCENTS = {
    "low": "#f5a524",
    "critical": "#f31260",
    "plugged": "#17c964",
    "unplugged": "#9aa4b2",
    "full": "#17c964",
    "info": "#7c8cff",
}


class NoticeBubble(QWidget):
    """Shows one notice at a time above (or below) the pet, fades in and out, click to open chat."""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._queue: deque[tuple[str, str]] = deque()
        self._text = ""
        self._accent = QColor(_ACCENTS["info"])
        self._below = False
        self._tail_x = 0.0
        self._pet = QRect()
        self._closing = False
        self._lines: list[str] = []
        self._font = QFont(self.font())
        self._font.setPixelSize(13)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.dismiss)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._on_faded)

    # -- public ------------------------------------------------------------------------------

    @property
    def showing(self) -> bool:
        return self.isVisible() and not self._closing

    @property
    def text(self) -> str:
        return self._text

    def notify(self, text: str, kind: str = "info") -> None:
        """Show ``text`` now, or after the current notice if one is on screen."""
        if self.showing:
            if len(self._queue) >= _QUEUE_MAX:
                self._queue.popleft()  # an old, unread notice matters less than the latest
            self._queue.append((text, kind))
            return
        self._show(text, kind)

    def anchor_to(self, pet: QRect) -> None:
        self._pet = QRect(pet)
        if self.isVisible():
            self._place()

    def dismiss(self) -> None:
        if not self.isVisible() or self._closing:
            return
        self._hide_timer.stop()
        self._closing = True
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def clear(self) -> None:
        self._queue.clear()
        self.dismiss()

    # -- internals ---------------------------------------------------------------------------

    def _show(self, text: str, kind: str) -> None:
        self._text = text
        self._accent = QColor(_ACCENTS.get(kind, _ACCENTS["info"]))
        self._closing = False
        self._layout_text()
        self._place()
        self._fade.stop()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._hide_timer.start(int(1000 * (_SECONDS_BASE + _SECONDS_PER_CHAR * len(text))))

    def _on_faded(self) -> None:
        if not self._closing:
            return
        self._closing = False
        self.hide()
        self.setWindowOpacity(1.0)
        if self._queue:
            self._show(*self._queue.popleft())

    def _layout_text(self) -> None:
        metrics = QFontMetrics(self._font)
        limit = _MAX_WIDTH - 2 * _PAD_X
        lines: list[str] = []
        for paragraph in self._text.splitlines() or [""]:
            line = ""
            for word in paragraph.split(" "):
                trial = f"{line} {word}".strip()
                if line and metrics.boundingRect(trial).width() > limit:
                    lines.append(line)
                    line = word
                else:
                    line = trial
            lines.append(line)
        if len(lines) > 4:
            lines = [
                *lines[:3],
                metrics.elidedText(" ".join(lines[3:]), Qt.TextElideMode.ElideRight, limit),
            ]
        self._lines = lines
        width = max(metrics.boundingRect(line).width() for line in lines) + 2 * _PAD_X
        height = len(lines) * metrics.lineSpacing() + 2 * _PAD_Y + _TAIL
        self.setFixedSize(max(width, 70), height)

    def _place(self) -> None:
        screen = QGuiApplication.screenAt(self._pet.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        above = self._pet.top() - self.height() - _GAP
        self._below = above < area.top()
        y = self._pet.bottom() + _GAP if self._below else above
        x = self._pet.center().x() - self.width() // 2
        x = max(area.left() + 4, min(x, area.right() - self.width() - 4))
        y = max(area.top(), min(y, area.bottom() - self.height()))
        self._tail_x = max(16.0, min(self.width() - 16.0, self._pet.center().x() - x))
        self.move(x, y)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.dismiss()
            self.clicked.emit()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = _TAIL if self._below else 0
        body = QRectF(1, top + 1, self.width() - 2, self.height() - _TAIL - 2)
        path = QPainterPath()
        path.addRoundedRect(body, 12, 12)
        tail = QPainterPath()
        if self._below:
            tail.moveTo(self._tail_x - 7, body.top())
            tail.lineTo(self._tail_x, 1)
            tail.lineTo(self._tail_x + 7, body.top())
        else:
            tail.moveTo(self._tail_x - 7, body.bottom())
            tail.lineTo(self._tail_x, self.height() - 1)
            tail.lineTo(self._tail_x + 7, body.bottom())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 245))
        painter.drawPath(path.united(tail))
        painter.setBrush(self._accent)  # accent strip on the left edge
        strip = QPainterPath()
        strip.addRoundedRect(QRectF(body.left(), body.top() + 7, 4, body.height() - 14), 2, 2)
        painter.drawPath(strip)
        painter.setPen(QPen(QColor(0, 0, 0, 30), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path.united(tail))
        painter.setPen(QColor("#1f2430"))
        painter.setFont(self._font)
        metrics = painter.fontMetrics()
        y = body.top() + _PAD_Y + metrics.ascent()
        for line in self._lines:
            painter.drawText(QPointF(body.left() + _PAD_X, y), line)
            y += metrics.lineSpacing()
