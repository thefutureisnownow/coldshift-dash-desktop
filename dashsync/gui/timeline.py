"""The strip under the video in Mix and export: the joined clips' time from left to right, with the trip log's
revs, speed and throttle drawn over it, where one clip ends and the next starts, the part chosen for export,
and where the player is. Clicking or dragging on it moves the player there."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

REVS = QColor("#ff8a65")
SPEED = QColor("#4fc3f7")
TRIM = QColor("#ffd54f")


def clock(s):
    s = max(0, int(s + 0.5))
    return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60) if s >= 3600 else "%d:%02d" % (s // 60, s % 60)


class Timeline(QWidget):
    seek = Signal(float)                    # seconds into the joined clips

    def __init__(self, parent=None):
        super().__init__(parent)
        self.total = 0.0
        self.bounds = []                    # where each clip after the first starts, in seconds
        self.samples = []                   # [(seconds, rpm, km/h, throttle %)]
        self.pos = 0.0
        self.start = self.end = None        # the part to export
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click or drag to move the video. The line is the engine's revs, the blue one the speed, "
                        "the shading the throttle (from the trip log).")

    def sizeHint(self):
        size = super().sizeHint()
        size.setHeight(110)
        return size

    def set_clips(self, total, bounds, samples):
        self.total, self.bounds, self.samples = total, bounds, samples
        self.update()

    def set_pos(self, s):
        self.pos = s
        self.update()

    def set_trim(self, start, end):
        self.start, self.end = start, end
        self.update()

    # ---- drawing ----

    def _x(self, s, area):
        return area.left() + (s / self.total if self.total else 0) * area.width()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)          # crisp, as the rest of the app
        pal = self.palette()
        text, base = pal.color(QPalette.WindowText), pal.color(QPalette.Base)
        area = QRectF(self.rect()).adjusted(1, 16, -1, -14)
        p.fillRect(area, base)
        if self.total <= 0:
            p.setPen(text)
            p.drawText(area, Qt.AlignCenter, "No clips")
            return
        # throttle as shading, then speed and revs as lines, each scaled to its own top
        rpm_top = max([r for _, r, _, _ in self.samples if r] + [1000.0])
        kmh_top = max([k for _, _, k, _ in self.samples if k] + [60.0])

        def y(v, top):
            return area.bottom() - (v / top) * (area.height() - 2) - 1

        if self.samples:
            shade = QColor(text)
            shade.setAlpha(40)
            for i in range(len(self.samples) - 1):
                t, _, _, thr = self.samples[i]
                t2 = self.samples[i + 1][0]
                if thr and t2 - t < 5:
                    x1, x2 = self._x(t, area), self._x(t2, area)
                    p.fillRect(QRectF(x1, y(thr, 100.0), max(1.0, x2 - x1), area.bottom() - y(thr, 100.0)), shade)
            for idx, colour, top in ((2, SPEED, kmh_top), (1, REVS, rpm_top)):
                path, gap = QPainterPath(), True
                last = None
                for s in self.samples:
                    v = s[idx]
                    if v is None or (last is not None and s[0] - last > 5):
                        gap = True
                    if v is None:
                        continue
                    pt = QPointF(self._x(s[0], area), y(v, top))
                    path.moveTo(pt) if gap else path.lineTo(pt)
                    gap, last = False, s[0]
                p.setPen(QPen(colour, 1.5))
                p.drawPath(path)
        # where the clips meet
        p.setPen(QPen(QColor(text.red(), text.green(), text.blue(), 70), 1, Qt.DashLine))
        for b in self.bounds:
            x = self._x(b, area)
            p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
        # outside the part to export
        if self.start is not None or self.end is not None:
            dim = QColor(0, 0, 0, 140)
            a, b = self._x(self.start or 0, area), self._x(self.end if self.end is not None else self.total, area)
            p.fillRect(QRectF(area.left(), area.top(), a - area.left(), area.height()), dim)
            p.fillRect(QRectF(b, area.top(), area.right() - b, area.height()), dim)
            p.setPen(QPen(TRIM, 2))
            for x in (a, b):
                p.drawLine(QPointF(x, area.top() - 3), QPointF(x, area.bottom() + 3))
        # the player
        x = self._x(self.pos, area)
        p.setPen(QPen(text, 2))
        p.drawLine(QPointF(x, area.top() - 4), QPointF(x, area.bottom() + 4))
        # words: the scales above, the time below
        p.setPen(text)
        f = p.font()
        f.setPointSizeF(max(8.0, f.pointSizeF() - 2))
        p.setFont(f)
        if self.samples:
            p.setPen(REVS)
            p.drawText(QRectF(4, 0, 200, 15), Qt.AlignLeft | Qt.AlignVCenter, "revs (top %d rpm)" % rpm_top)
            p.setPen(SPEED)
            p.drawText(QRectF(170, 0, 200, 15), Qt.AlignLeft | Qt.AlignVCenter, "speed (top %d km/h)" % kmh_top)
        else:
            p.drawText(QRectF(4, 0, 600, 15), Qt.AlignLeft | Qt.AlignVCenter,
                       "No trip log here for these clips (Sync to PC copies it)")
        p.setPen(text)
        step = next((s for s in (10, 30, 60, 120, 300, 600, 1800) if self.total / s <= 12), 3600)
        t = 0
        while t <= self.total:
            x = self._x(t, area)
            p.drawLine(QPointF(x, area.bottom()), QPointF(x, area.bottom() + 3))
            box = QRectF(x - 30, area.bottom() + 1, 60, 13)
            box.moveLeft(max(0.0, min(self.width() - 60.0, box.left())))     # the first and last stay whole
            p.drawText(box, Qt.AlignCenter if 0 < box.left() < self.width() - 60 else
                       (Qt.AlignLeft if box.left() <= 0 else Qt.AlignRight), clock(t))
            t += step

    # ---- seeking ----

    def _seek_to(self, x):
        area = QRectF(self.rect()).adjusted(1, 16, -1, -14)
        if self.total > 0 and area.width() > 0:
            self.seek.emit(max(0.0, min(self.total, (x - area.left()) / area.width() * self.total)))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._seek_to(e.position().x())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._seek_to(e.position().x())
