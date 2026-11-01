"""The built-in characters, drawn entirely in code (no image files).

Each character supplies a *body* painter and where its face sits. The face itself (eyes, mouth,
every emotion, blinking, following the pointer) is shared and lives in ``pet.py``, so every
character here reacts the same way and stays sharp at any size.

All painters draw in a 120 x 120 space with the feet on y = 104.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)

from assistant.ui.state import Mood

LAMP: dict[Mood, QColor] = {
    Mood.IDLE: QColor("#5be37d"),
    Mood.THINKING: QColor("#ffc247"),
    Mood.TALKING: QColor("#5bc8ff"),
    Mood.ASKING: QColor("#b88cff"),
    Mood.ERROR: QColor("#ff5b5b"),
}

BodyPainter = Callable[[QPainter, QColor, float, bool], None]  # painter, lamp, phase, active
_NO_PEN = Qt.PenStyle.NoPen


@dataclass(frozen=True)
class VectorCharacter:
    key: str
    name: str
    tagline: str
    paint_body: BodyPainter
    face_center: tuple[float, float]  # where the middle of the face goes, in the 120 x 120 space
    face_scale: float  # 1.0 = the robot's face size
    ink: QColor  # eyes, mouth and brows
    paper: QColor  # the colour under the eyes (shows in the pupils of wide-open eyes)
    shine: bool = False  # a small highlight in each eye
    mouth: bool = True  # False when the artwork already has a beak or similar


# -- shared shapes and helpers --------------------------------------------------------------------


def heart_path(size: float) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(0, size)
    path.cubicTo(-size * 1.6, -size * 0.2, -size * 0.7, -size * 1.5, 0, -size * 0.5)
    path.cubicTo(size * 0.7, -size * 1.5, size * 1.6, -size * 0.2, 0, size)
    return path


def sparkle_path(size: float) -> QPainterPath:
    path = QPainterPath()
    for i in range(8):
        radius = size if i % 2 == 0 else size * 0.28
        angle = math.pi / 4 * i - math.pi / 2
        point = QPointF(math.cos(angle) * radius, math.sin(angle) * radius)
        if i == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    return path


def _pen(color: QColor | str, width: float) -> QPen:
    return QPen(
        QColor(color),
        width,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )


def _poly(points: Sequence[tuple[float, float]]) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in points])


def _mirror(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    return [(120 - x, y) for x, y in points]


def _vgrad(top: float, bottom: float, c1: str, c2: str, alpha: int = 255) -> QBrush:
    gradient = QLinearGradient(0, top, 0, bottom)
    first, second = QColor(c1), QColor(c2)
    first.setAlpha(alpha)
    second.setAlpha(alpha)
    gradient.setColorAt(0, first)
    gradient.setColorAt(1, second)
    return QBrush(gradient)


def _ears(
    p: QPainter,
    outer: Sequence[tuple[float, float]],
    inner: Sequence[tuple[float, float]],
    fill: QColor | str,
    edge: QColor | str,
    inner_fill: QColor | str,
) -> None:
    """A pair of pointed ears; ``outer`` and ``inner`` describe the left one, the right is mirrored."""
    for flip in (False, True):
        o, i = (_mirror(outer), _mirror(inner)) if flip else (outer, inner)
        p.setBrush(QColor(fill))
        p.setPen(_pen(edge, 2.2))
        p.drawPolygon(_poly(o))
        p.setPen(_NO_PEN)
        p.setBrush(QColor(inner_fill))
        p.drawPolygon(_poly(i))


def _highlight(
    p: QPainter, x: float, y: float, rx: float, ry: float, angle: float, alpha: int = 140
) -> None:
    p.save()
    p.setPen(_NO_PEN)
    p.setBrush(QColor(255, 255, 255, alpha))
    p.translate(x, y)
    p.rotate(angle)
    p.drawEllipse(QRectF(-rx, -ry, rx * 2, ry * 2))
    p.restore()


def lamp_gem(
    p: QPainter, x: float, y: float, radius: float, lamp: QColor, phase: float, active: bool
) -> None:
    """The mood light: a soft glow around a glossy gem."""
    pulse = 0.65 + 0.35 * math.sin(phase * (4 if active else 1.5))
    glow = QRadialGradient(QPointF(x, y), radius * 2.8)
    centre = QColor(lamp)
    centre.setAlphaF(0.55 * pulse)
    edge = QColor(lamp)
    edge.setAlpha(0)
    glow.setColorAt(0, centre)
    glow.setColorAt(1, edge)
    p.setPen(_NO_PEN)
    p.setBrush(QBrush(glow))
    p.drawEllipse(QPointF(x, y), radius * 2.8, radius * 2.8)
    p.setBrush(lamp)
    p.drawEllipse(QPointF(x, y), radius, radius)
    p.setBrush(QColor(255, 255, 255, 175))
    p.drawEllipse(QPointF(x - radius * 0.3, y - radius * 0.35), radius * 0.32, radius * 0.32)


def _shadowed_body(
    p: QPainter, rect: QRectF, radius: float, top: str, bottom: str, edge: str
) -> None:
    p.setBrush(_vgrad(rect.top(), rect.bottom(), top, bottom))
    p.setPen(QPen(QColor(edge), 2.5))
    p.drawRoundedRect(rect, radius, radius)


# -- the characters -------------------------------------------------------------------------------


def _robot(p: QPainter, lamp: QColor, phase: float, active: bool) -> None:
    edge = QColor("#2f46a0")
    p.setPen(_pen(edge, 3))
    p.drawLine(QPointF(60, 34), QPointF(60, 20))
    lamp_gem(p, 60, 17, 5.5, lamp, phase, active)
    p.setPen(_NO_PEN)
    p.setBrush(edge)
    p.drawEllipse(QPointF(15, 68), 8, 11)
    p.drawEllipse(QPointF(105, 68), 8, 11)
    _shadowed_body(p, QRectF(20, 33, 80, 70), 28, "#7fa4ff", "#4a69d8", "#2f46a0")
    _highlight(p, 38, 42, 12, 4, -12, 90)
    p.setPen(_NO_PEN)
    p.setBrush(QColor("#0e1633"))
    p.drawRoundedRect(QRectF(29, 47, 62, 38), 16, 16)


def _nexo(p: QPainter, lamp: QColor, phase: float, active: bool) -> None:
    edge, cyan = QColor("#8ea3d8"), QColor("#2fd6ff")
    _ears(p, [(27, 48), (31, 12), (54, 34)], [(34, 41), (36, 24), (47, 35)], "#f1f5ff", edge, cyan)
    _shadowed_body(p, QRectF(20, 33, 80, 70), 30, "#ffffff", "#c9d6f1", "#8ea3d8")
    _highlight(p, 40, 40, 12, 4, -12)
    for cx in (15, 105):  # headphones
        p.setBrush(QColor("#e4ecff"))
        p.setPen(_pen(edge, 2.2))
        p.drawEllipse(QPointF(cx, 70), 8, 14)
        p.setPen(_NO_PEN)
        p.setBrush(cyan)
        p.drawEllipse(QPointF(cx, 70), 4, 9)
        p.setBrush(QColor(255, 255, 255, 170))
        p.drawEllipse(QPointF(cx - 1, 66), 1.3, 3)
    p.setBrush(QColor("#0a1126"))  # visor
    p.setPen(QPen(QColor(47, 214, 255, 120), 1.4))
    p.drawRoundedRect(QRectF(27, 45, 66, 43), 20, 20)
    p.setPen(_NO_PEN)
    p.setBrush(cyan)
    p.drawRoundedRect(QRectF(52, 95, 16, 3), 1.5, 1.5)
    lamp_gem(p, 60, 40, 3.4, lamp, phase, active)


def _kiko(p: QPainter, lamp: QColor, phase: float, active: bool) -> None:
    edge = QColor("#9b8cdc")
    p.save()  # the big fluffy tail, swishing a little
    p.translate(92, 92)
    p.rotate(-42 + math.sin(phase * (2.4 if active else 1.2)) * 6)
    p.setBrush(_vgrad(-12, 12, "#aeeaff", "#4fa6ee"))
    p.setPen(QPen(QColor("#3f8ad4"), 2))
    p.drawEllipse(QRectF(-4, -12, 44, 24))
    p.setPen(_NO_PEN)
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(QRectF(24, -10, 16, 20))
    p.restore()
    _ears(
        p, [(24, 52), (26, 8), (56, 36)], [(32, 44), (31, 21), (47, 36)], "#b9a8f3", edge, "#cdeeff"
    )
    _shadowed_body(p, QRectF(17, 34, 86, 70), 36, "#ffffff", "#dcd3fa", "#9b8cdc")
    _highlight(p, 38, 42, 13, 4, -12, 150)
    p.setBrush(QColor("#ffffff"))  # cheek fluff
    p.setPen(_pen(edge, 2))
    for pts in ([(19, 63), (6, 70), (20, 74)], [(19, 75), (7, 83), (21, 87)]):
        p.drawPolygon(_poly(pts))
        p.drawPolygon(_poly(_mirror(pts)))
    p.setPen(_NO_PEN)
    p.setBrush(QColor("#1c2a66"))  # nose
    p.drawEllipse(QPointF(60, 68), 2.8, 2.1)
    p.setBrush(QColor("#3b6fe0"))  # collar
    p.drawRoundedRect(QRectF(34, 92, 52, 7), 3.5, 3.5)
    lamp_gem(p, 60, 99, 4.2, lamp, phase, active)
    lamp_gem(p, 60, 41, 2.6, QColor("#60dcff"), phase, False)


def _momo(p: QPainter, lamp: QColor, phase: float, active: bool) -> None:
    cyan = QColor("#35d6ff")
    wag = math.sin(phase * (2.4 if active else 1.1)) * 4
    tail = QPainterPath(QPointF(30, 100))  # the curling tail, glowing at the tip
    tail.cubicTo(QPointF(4, 98 + wag), QPointF(2, 66), QPointF(17, 58 + wag))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen("#0f1426", 9))
    p.drawPath(tail)
    p.setPen(_NO_PEN)
    p.setBrush(cyan)
    p.drawEllipse(QPointF(17, 58 + wag), 4.8, 4.8)
    _ears(
        p,
        [(27, 50), (30, 10), (55, 35)],
        [(34, 42), (34, 21), (47, 36)],
        "#10152a",
        "#05070f",
        "#1dbbff",
    )
    _shadowed_body(p, QRectF(19, 34, 82, 70), 34, "#222a52", "#0b0f1f", "#05070f")
    p.setBrush(Qt.BrushStyle.NoBrush)  # rim light
    p.setPen(_pen(QColor(53, 214, 255, 110), 1.6))
    p.drawArc(QRectF(23, 38, 74, 62), 105 * 16, 80 * 16)
    p.setPen(_pen(QColor(53, 214, 255, 120), 1.2))  # whiskers
    for dy, tip in ((70, 66), (75, 76)):
        p.drawLine(QPointF(23, dy), QPointF(9, tip))
        p.drawLine(QPointF(97, dy), QPointF(111, tip))
    p.setPen(_NO_PEN)
    p.setBrush(QColor(28, 202, 255, 230))
    p.drawRoundedRect(QRectF(35, 92, 50, 5), 2.5, 2.5)
    lamp_gem(p, 60, 100, 4.8, lamp, phase, active)


def _lumi(p: QPainter, lamp: QColor, phase: float, active: bool) -> None:
    bob = math.sin(phase * 1.3) * 1.5
    ring = QRectF(6, 70, 108, 24)
    p.save()
    p.translate(60, 82)
    p.rotate(-12)
    p.translate(-60, -82)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(QColor(190, 240, 255, 120), 2.6))
    p.drawArc(ring, 0, 180 * 16)  # the back of the ring, behind the body
    p.restore()

    body = QPainterPath(QPointF(22, 74))
    body.cubicTo(22, 48, 40, 34, 60, 34)
    body.cubicTo(80, 34, 98, 48, 98, 74)
    body.lineTo(98, 92)
    body.cubicTo(96, 102, 86, 106, 80, 98)
    body.cubicTo(74, 106, 66, 106, 60, 98)
    body.cubicTo(54, 106, 46, 106, 40, 98)
    body.cubicTo(34, 106, 24, 102, 22, 92)
    body.closeSubpath()
    p.save()
    p.translate(0, bob)
    p.setBrush(_vgrad(34, 104, "#e6faff", "#69b2ff", 232))
    p.setPen(QPen(QColor(240, 253, 255, 210), 2))
    p.drawPath(body)
    p.setPen(_NO_PEN)
    p.setBrush(QColor("#cdf3ff"))  # the little tuft
    p.save()
    p.translate(68, 29)
    p.rotate(25)
    p.drawEllipse(QRectF(-7, -5, 14, 10))
    p.restore()
    _highlight(p, 38, 46, 13, 5, -22, 120)
    for i, (x, y) in enumerate(((16, 46), (104, 40), (98, 92))):  # drifting sparkles
        twinkle = 0.5 + 0.5 * math.sin(phase * 1.8 + i * 2.1)
        p.setBrush(QColor(255, 255, 255, int(110 + 130 * twinkle)))
        p.save()
        p.translate(x, y)
        p.drawPath(sparkle_path(2.5 + 2.5 * twinkle))
        p.restore()
    lamp_gem(p, 60, 90, 3.6, lamp, phase, active)
    p.restore()

    p.save()
    p.translate(60, 82)
    p.rotate(-12)
    p.translate(-60, -82)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(QColor(215, 248, 255, 200), 2.8))
    p.drawArc(ring, 180 * 16, 180 * 16)  # the front of the ring
    p.restore()


def _zen(p: QPainter, lamp: QColor, phase: float, active: bool) -> None:
    green, dark = QColor("#4ccf45"), QColor("#2f9a31")
    sway = math.sin(phase * 1.6) * 2
    for sign, x in ((-1, 46), (1, 74)):  # antennae
        tip = QPointF(60 + sign * 24 + sway * sign, 15)
        p.setPen(_pen(dark, 3))
        p.drawLine(QPointF(x, 38), tip)
        if sign == -1:
            p.setPen(_NO_PEN)
            p.setBrush(QColor("#d3ff8a"))
            p.drawEllipse(tip, 5.5, 5.5)
        else:
            lamp_gem(p, tip.x(), tip.y(), 5.2, lamp, phase, active)
    p.setPen(_NO_PEN)
    p.setBrush(dark)
    for cx in (38, 82):  # feet
        p.drawEllipse(QPointF(cx, 103), 11, 5)
    p.setBrush(green)
    for cx, angle in ((11, 18), (109, -18)):  # little arms
        p.save()
        p.translate(cx, 80)
        p.rotate(angle)
        p.setPen(QPen(dark, 2))
        p.drawEllipse(QRectF(-6, -9, 12, 18))
        p.restore()
    _shadowed_body(p, QRectF(15, 30, 90, 74), 40, "#aaff85", "#46c943", "#2f9a31")
    _highlight(p, 38, 40, 13, 4.5, -14, 130)


def _owlly(p: QPainter, lamp: QColor, phase: float, active: bool) -> None:
    navy, cyan = QColor("#2c3f8f"), QColor("#29c8ff")
    flap = math.sin(phase * (3.0 if active else 1.0)) * 4
    for sign, cx in ((1, 14), (-1, 106)):  # wings
        p.save()
        p.translate(cx, 72)
        p.rotate(sign * (8 + flap))
        p.setBrush(navy)
        p.setPen(QPen(QColor("#1c2a66"), 2))
        p.drawEllipse(QRectF(-9, -22, 18, 44))
        p.restore()
    p.setPen(_NO_PEN)
    p.setBrush(QColor("#ffb43a"))
    for cx in (47, 73):  # feet
        p.drawEllipse(QPointF(cx, 103), 8, 3.4)
    p.setBrush(navy)  # ear tufts
    p.setPen(_pen("#1c2a66", 2))
    for pts in ([(30, 40), (23, 12), (47, 32)],):
        p.drawPolygon(_poly(pts))
        p.drawPolygon(_poly(_mirror(pts)))
    _shadowed_body(p, QRectF(22, 30, 76, 74), 36, "#f8faff", "#cdd8f5", "#8da0d6")
    p.setBrush(Qt.BrushStyle.NoBrush)  # feather scallops on the belly
    p.setPen(_pen(QColor("#9fb4ec"), 1.7))
    for y, xs in ((88, (44, 60, 76)), (95, (52, 68))):
        for x in xs:
            p.drawArc(QRectF(x - 6, y, 12, 9), 200 * 16, 140 * 16)
    for cx in (43, 77):  # big round eyes
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(cyan, 3.2))
        p.drawEllipse(QPointF(cx, 58), 15.5, 15.5)
    p.setBrush(QColor("#ffb43a"))  # beak
    p.setPen(_pen("#d98a14", 1.6))
    p.drawPolygon(_poly([(55, 64), (65, 64), (60, 74)]))
    lamp_gem(p, 60, 84, 3.4, lamp, phase, active)


def _slimey(p: QPainter, lamp: QColor, phase: float, active: bool) -> None:
    wobble = math.sin(phase * (3.2 if active else 1.6)) * 0.025
    p.save()
    p.translate(60, 104)
    p.scale(1 + wobble, 1 - wobble)
    p.translate(-60, -104)
    blue = QColor("#2f86f0")
    p.setPen(_NO_PEN)
    p.setBrush(_vgrad(60, 104, "#8fdcff", "#3b8ff0", 235))
    for x, y, r in ((7, 100, 6), (114, 98, 5)):  # little droplets
        p.drawEllipse(QPointF(x, y), r, r * 0.9)
    body = QPainterPath(QPointF(8, 104))
    body.cubicTo(8, 66, 36, 36, 60, 36)
    body.cubicTo(84, 36, 112, 66, 112, 104)
    body.cubicTo(90, 107, 30, 107, 8, 104)
    body.closeSubpath()
    p.setBrush(_vgrad(36, 106, "#9be4ff", "#3585ee", 238))
    p.setPen(QPen(blue.darker(125), 2.4))
    p.drawPath(body)
    _highlight(p, 34, 54, 14, 6, -32, 150)
    _highlight(p, 50, 45, 3.5, 3.5, 0, 170)
    p.setPen(_NO_PEN)
    p.setBrush(QColor(255, 255, 255, 60))  # the glossy rim at the bottom
    p.drawEllipse(QRectF(24, 96, 72, 7))
    p.restore()
    lamp_gem(p, 66, 31, 4.2, lamp, phase, active)


def _pupbot(p: QPainter, lamp: QColor, phase: float, active: bool) -> None:
    blue, edge = QColor("#3b5bdb"), QColor("#a4b4de")
    wag = math.sin(phase * (7.0 if active else 4.5)) * 24
    p.save()  # wagging tail
    p.translate(103, 95)
    p.rotate(-35 + wag)
    p.setBrush(QColor("#ffffff"))
    p.setPen(QPen(edge, 2))
    p.drawEllipse(QRectF(0, -4, 16, 8))
    p.setPen(_NO_PEN)
    p.setBrush(QColor("#4fd8ff"))
    p.drawEllipse(QRectF(10, -3.2, 6, 6.4))
    p.restore()
    sway = math.sin(phase * 1.5) * 2
    for sign, cx in ((1, 20), (-1, 100)):  # floppy ears
        p.save()
        p.translate(cx, 52)
        p.rotate(sign * (14 + sway))
        p.setBrush(QColor("#2b46b8"))
        p.setPen(QPen(QColor("#1a2c80"), 2))
        p.drawEllipse(QRectF(-11, -4, 22, 44))
        p.setPen(_NO_PEN)
        p.setBrush(QColor(79, 216, 255, 200))
        p.drawEllipse(QRectF(-3.5, 2, 7, 28))
        p.restore()
    body_rect = QRectF(22, 34, 76, 70)
    _shadowed_body(p, body_rect, 32, "#ffffff", "#e1e8fa", "#a4b4de")
    clip = QPainterPath()
    clip.addRoundedRect(body_rect, 32, 32)
    p.save()  # the blue patch over one side of the head
    p.setClipPath(clip)
    p.setPen(_NO_PEN)
    p.setBrush(blue)
    p.drawEllipse(QPointF(90, 42), 22, 17)
    p.setBrush(QColor(79, 216, 255, 220))
    for x, y in ((84, 40), (93, 46), (88, 34)):
        p.drawEllipse(QPointF(x, y), 1.8, 1.8)
    p.restore()
    _highlight(p, 40, 42, 11, 4, -12, 140)
    p.setPen(QPen(QColor("#c3cfee"), 1.6))  # snout
    p.setBrush(QColor("#f6f8ff"))
    p.drawEllipse(QPointF(60, 72), 15, 11)
    p.setPen(_NO_PEN)
    p.setBrush(QColor("#ff7fa0"))  # tongue
    p.drawRoundedRect(QRectF(58, 74, 8, 9), 4, 4)
    p.setBrush(QColor("#1c2a66"))  # nose
    p.drawEllipse(QPointF(60, 64.5), 4.6, 3.4)
    p.setBrush(QColor(255, 255, 255, 190))
    p.drawEllipse(QPointF(58.6, 63.4), 1.2, 0.9)
    p.setBrush(QColor("#2b8cff"))  # collar
    p.drawRoundedRect(QRectF(34, 92, 52, 6), 3, 3)
    lamp_gem(p, 60, 100, 4.5, lamp, phase, active)


ROBOT = VectorCharacter(
    "robot", "Robot", "The original", _robot, (60, 68), 1.0, QColor("#9ff3ff"), QColor("#0e1633")
)
CHARACTERS: dict[str, VectorCharacter] = {
    c.key: c
    for c in (
        ROBOT,
        VectorCharacter(
            "nexo",
            "Nexo",
            "The Loyal Robot Companion",
            _nexo,
            (60, 68),
            1.0,
            QColor("#5ae6ff"),
            QColor("#0a1126"),
        ),
        VectorCharacter(
            "kiko",
            "Kiko",
            "The Curious Fox",
            _kiko,
            (60, 66),
            1.05,
            QColor("#1c2a66"),
            QColor("#ffffff"),
            shine=True,
        ),
        VectorCharacter(
            "momo",
            "Momo",
            "The Digital Cat",
            _momo,
            (60, 66),
            1.12,
            QColor("#3ee4ff"),
            QColor("#0b0f1f"),
            shine=True,
        ),
        VectorCharacter(
            "lumi",
            "Lumi",
            "The Holographic Spirit",
            _lumi,
            (60, 66),
            1.1,
            QColor("#12407f"),
            QColor("#ffffff"),
            shine=True,
        ),
        VectorCharacter(
            "zen",
            "ZEN",
            "The Little Alien",
            _zen,
            (60, 68),
            1.45,
            QColor("#08101f"),
            QColor("#ffffff"),
            shine=True,
        ),
        VectorCharacter(
            "owlly",
            "Owlly",
            "The Cyber Owl",
            _owlly,
            (60, 65.2),
            1.2,
            QColor("#0e2a6b"),
            QColor("#ffffff"),
            shine=True,
            mouth=False,
        ),
        VectorCharacter(
            "slimey",
            "Slimey",
            "The AI Slime",
            _slimey,
            (60, 76),
            1.05,
            QColor("#0b1f4d"),
            QColor("#ffffff"),
            shine=True,
        ),
        VectorCharacter(
            "pupbot",
            "PupBot",
            "The Robo Pup",
            _pupbot,
            (60, 64),
            1.0,
            QColor("#1c2a66"),
            QColor("#ffffff"),
            shine=True,
        ),
    )
}
