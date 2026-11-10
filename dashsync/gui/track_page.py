"""Track page: the vehicle's track segments and runs from the phone (dashsync/track.py). Compare two runs
over the distance, rename and share segments, import someone else's, and share a run with its clip."""
import datetime
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import paths, track
from . import forms, worker

SID, RUN = Qt.UserRole, Qt.UserRole + 1
A_COL, B_COL = QColor("#9aa7b8"), QColor("#2f7bff")


def map_pixmap(s, size=240):
    """The segment north up as the app's track map draws it: outline, green start, chequered finish."""
    out = QPixmap(size, size)
    out.fill(QColor("#0b1424"))
    pts = s["points"]
    cos = __import__("math").cos(__import__("math").radians(pts[0][0]))
    xs = [p[1] * cos for p in pts]
    ys = [-p[0] for p in pts]
    w, h = max(max(xs) - min(xs), 1e-9), max(max(ys) - min(ys), 1e-9)
    pad = 20
    k = min((size - 2 * pad) / w, (size - 2 * pad) / h)
    ox, oy = size / 2 - (min(xs) + w / 2) * k, size / 2 - (min(ys) + h / 2) * k
    path = QPainterPath(QPointF(xs[0] * k + ox, ys[0] * k + oy))
    for x, y in zip(xs[1:], ys[1:]):
        path.lineTo(x * k + ox, y * k + oy)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(255, 255, 255, 64), 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPath(path)
    p.setPen(QPen(QColor("#dfe8f7"), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#46d17a"))
    p.drawEllipse(QPointF(xs[0] * k + ox, ys[0] * k + oy), 7, 7)
    if not s["lap"]:
        x, y = xs[-1] * k + ox, ys[-1] * k + oy
        for i in range(4):
            p.setBrush(QColor("#ffffff") if i % 2 == 0 else QColor("#111111"))
            p.drawRect(QRectF(x - 8 + (i % 2) * 8, y - 8 + (i // 2) * 8, 8, 8))
    p.end()
    return out


class CompareChart(QWidget):
    """Two runs over the distance: their speeds, and the time between them (up and green where the second
    is ahead, down and red where it is behind)."""
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(230)
        self.rows, self.labels = [], ("", "")

    def show_runs(self, rows, labels):
        self.rows, self.labels = rows, labels
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        text, grid = pal.color(pal.ColorRole.WindowText), pal.color(pal.ColorRole.Mid)
        if len(self.rows) < 2:
            p.setPen(pal.color(pal.ColorRole.PlaceholderText))
            p.drawText(self.rect(), Qt.AlignCenter, "Select two runs to compare them over the distance.")
            p.end()
            return
        left, right, top = 86, self.width() - 16, 40
        mid = top + (self.height() - top - 30) * 0.55
        bottom = self.height() - 30
        dmax = self.rows[-1][0] or 1
        vmax = max(max(r[2], r[3]) for r in self.rows) * 1.1 or 1
        gap = max(abs(r[1]) for r in self.rows) or 0.5
        x = lambda m: left + (right - left) * m / dmax
        # legend
        p.setPen(A_COL)
        p.drawText(left, 16, "— first: " + self.labels[0])
        p.setPen(B_COL)
        p.drawText(left + 260, 16, "— second: " + self.labels[1])
        # speed panel
        p.setPen(QPen(grid, 1, Qt.DotLine))
        for v in range(0, int(vmax) + 1, 20 if vmax > 60 else 10):
            y = mid - (mid - top) * v / vmax
            p.drawLine(left, y, right, y)
            p.setPen(text)
            p.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter, "%d" % v)
            p.setPen(QPen(grid, 1, Qt.DotLine))
        for col, idx in ((A_COL, 2), (B_COL, 3)):
            path = QPainterPath(QPointF(x(self.rows[0][0]), mid - (mid - top) * self.rows[0][idx] / vmax))
            for r in self.rows[1:]:
                path.lineTo(x(r[0]), mid - (mid - top) * r[idx] / vmax)
            p.setPen(QPen(col, 2))
            p.drawPath(path)
        p.setPen(text)
        p.drawText(QRectF(0, top - 24, left - 6, 14), Qt.AlignRight, "km/h")
        # time-between panel: below the line = the second run ahead
        zero = mid + 10 + (bottom - mid - 10) / 2
        span = (bottom - mid - 10) / 2
        p.setPen(QPen(grid, 1))
        p.drawLine(left, zero, right, zero)
        p.setPen(text)
        p.drawText(QRectF(0, zero - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter, "0 s")
        p.drawText(QRectF(0, mid + 6, left - 6, 16), Qt.AlignRight, "%.1f s ahead" % gap)
        p.drawText(QRectF(0, bottom - 16, left - 6, 16), Qt.AlignRight, "%.1f s behind" % gap)
        for (m0, g0, *_), (m1, g1, *_) in zip(self.rows, self.rows[1:]):
            colour = QColor("#46d17a") if (g0 + g1) / 2 <= 0 else QColor("#e5534b")
            p.setPen(QPen(colour, 2.5))
            p.drawLine(QPointF(x(m0), zero + span * g0 / gap), QPointF(x(m1), zero + span * g1 / gap))
        # distance axis
        p.setPen(text)
        step = 100 if dmax < 1500 else 500 if dmax < 6000 else 1000
        m = 0
        while m <= dmax:
            p.drawText(QRectF(x(m) - 30, bottom + 4, 60, 16), Qt.AlignHCenter, "%d m" % m if m < 1000 else "%.1f km" % (m / 1000))
            m += step
        end = self.rows[-1][1]
        p.drawText(QRectF(left, bottom - 34, right - left, 16), Qt.AlignRight,
                   "At the finish the second is %.2f s %s" % (abs(end), "ahead" if end < 0 else "behind"))
        p.end()


class TrackPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.segs = []

        top = QHBoxLayout()
        self.pull_btn = QPushButton("Sync to PC")
        self.pull_btn.setToolTip("Copy the phone's segments and runs into this vehicle")
        self.pull_btn.clicked.connect(self.sync_to_pc)
        self.push_btn = QPushButton("Sync to card")
        self.push_btn.setToolTip("Put this vehicle's segments on the phone (new and renamed ones; the app adds them)")
        self.push_btn.clicked.connect(self.sync_to_card)
        self.note = QLabel()
        self.note.setWordWrap(True)
        top.addWidget(self.pull_btn)
        top.addWidget(self.push_btn)
        top.addWidget(self.note, 1)

        left = QGroupBox("Segments")
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        ll = QVBoxLayout(left)
        ll.addWidget(self.list, 1)
        r1, r2 = QHBoxLayout(), QHBoxLayout()
        self.btns = {}
        for row, (text, fn, tip) in ((r1, ("Import…", self.import_segment, "A segment someone shared (.segment.json or GPX)")),
                                     (r1, ("Export…", self.export_segment, "Save the segment to share")),
                                     (r1, ("GPX…", self.export_gpx, "The segment's path as GPX, for other tools")),
                                     (r2, ("Rename…", self.rename, "")),
                                     (r2, ("Delete", self.delete, "Off this computer (delete it on the phone too)"))):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.btns[text] = b
        r2.addStretch()
        ll.addLayout(r1)
        ll.addLayout(r2)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.map = QLabel()
        self.map.setFixedSize(150, 150)
        info = QVBoxLayout()
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 18px; font-weight: 600")
        self.sub = forms.note("")
        self.best = QLabel()
        self.best.setStyleSheet("font-size: 28px; font-weight: 700")
        info.addWidget(self.title)
        info.addWidget(self.sub)
        info.addWidget(self.best)
        info.addStretch()
        head.addWidget(self.map)
        head.addLayout(info, 1)
        rl.addLayout(head)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["When", "Lap", "Time", "Gap to best", "Clip"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._runs_selected)
        self.table.setMinimumHeight(150)
        rl.addWidget(self.table, 1)
        rb = QHBoxLayout()
        self.share_btn = QPushButton("Share run…")
        self.share_btn.setToolTip("A folder with the run's clip, GPX and CSV (for overlay tools and friends)")
        self.share_btn.clicked.connect(self.share_run)
        self.clip_btn = QPushButton("Show clip")
        self.clip_btn.clicked.connect(self.show_clip)
        rb.addWidget(self.share_btn)
        rb.addWidget(self.clip_btn)
        rb.addWidget(forms.note("Select two runs to compare them."), 1)
        rl.addLayout(rb)
        self.chart = CompareChart()
        rl.addWidget(self.chart)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([320, 700])
        # nothing yet: say how segments get here instead of showing empty lists
        self.first_pull = QPushButton("Sync to PC")
        self.first_pull.setDefault(True)
        self.first_pull.clicked.connect(self.sync_to_pc)
        first_import = QPushButton("Import…")
        first_import.setToolTip("A segment someone shared (.segment.json or GPX)")
        first_import.clicked.connect(self.import_segment)
        empty, _ = forms.empty("No segments yet", "Record a segment on the phone's Track page, then bring it here "
                               "with Sync to PC. Or import one someone shared.", self.first_pull, first_import)
        self.body = QStackedWidget()
        self.body.addWidget(empty)
        self.body.addWidget(split)
        page = QVBoxLayout(self)
        page.addWidget(self.body, 1)
        page.addLayout(top)
        state.busy_changed.connect(self._buttons)
        state.target_changed.connect(self._buttons)
        self.load()

    def vehicle(self):
        return paths.load_config().get("workspace")

    def recordings(self):
        return track.recordings_dir(paths.load_config())

    def showEvent(self, e):
        super().showEvent(e)
        self.load(self._sid())

    def load(self, select=None):
        v = self.vehicle()
        self.segs = track.segments(v) if v else []
        self.list.blockSignals(True)
        self.list.clear()
        for s in self.segs:
            it = QListWidgetItem("%s\n%s · %.0f m · %s" % (
                s["name"], "Lap" if s["lap"] else "Point to point", s["length"],
                ("best %s of %d" % (track.time_text(s["best_ms"] / 1000), s["runs"])) if s["runs"] else "no runs"))
            it.setData(SID, s["id"])
            self.list.addItem(it)
            if s["id"] == select:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._select()
        self.body.setCurrentIndex(1 if self.segs else 0)

    def _sid(self):
        it = self.list.currentItem()
        return it.data(SID) if it else None

    def _seg(self):
        sid = self._sid()
        return next((s for s in self.segs if s["id"] == sid), None)

    def _select(self, *_):
        s = self._seg()
        self.table.setRowCount(0)
        self.chart.show_runs([], ("", ""))
        if not s:
            self.title.setText("")
            self.sub.setText("")
            self.best.setText("")
            self.map.setPixmap(QPixmap())
            self._buttons()
            return
        self.title.setText(s["name"])
        self.sub.setText("%s · %.0f m" % ("Lap" if s["lap"] else "Point to point", s["length"]))
        self.best.setText(track.time_text(s["best_ms"] / 1000) if s["best_ms"] else "No runs yet")
        self.map.setPixmap(map_pixmap(s, 150))
        rs = track.runs(self.vehicle(), s["id"])
        rec = self.recordings()
        self.table.setRowCount(len(rs))
        for i, r in enumerate(rs):
            when = datetime.datetime.fromtimestamp(r["start"] / 1000).strftime("%a %d %b %Y  %H:%M")
            gap = r["time_ms"] - s["best_ms"] if s["best_ms"] else 0
            clip = track.clip(rec, r.get("mark"))
            cells = [when, str(r["lap"]) if r.get("lap") else "", track.time_text(r["time_ms"] / 1000),
                     "best" if gap == 0 else "+%.1f s" % (gap / 1000),
                     "on this computer" if clip else ("mark %d, not copied yet" % r["mark"] if r.get("mark") else "")]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setData(RUN, r["file"])
                self.table.setItem(i, c, it)
        self._buttons()

    def _selected_runs(self):
        s = self._seg()
        if not s:
            return []
        files = []
        for idx in self.table.selectionModel().selectedRows():
            files.append(self.table.item(idx.row(), 0).data(RUN))
        rs = {r["file"]: r for r in track.runs(self.vehicle(), s["id"])}
        return [rs[f] for f in files if f in rs]

    def _runs_selected(self):
        s, sel = self._seg(), self._selected_runs()
        if s and len(sel) == 2:
            a, b = sorted(sel, key=lambda r: r["start"])
            label = lambda r: "%s %s" % (datetime.datetime.fromtimestamp(r["start"] / 1000).strftime("%H:%M"),
                                         track.time_text(r["time_ms"] / 1000))
            self.chart.show_runs(track.compare(a, b, s["length"]), (label(a), label(b)))
        else:
            self.chart.show_runs([], ("", ""))
        self._buttons()

    def _buttons(self):
        v, s, sel = self.vehicle(), self._seg(), self._selected_runs() if self._seg() else []
        ok = bool(v) and self.state.has_target() and not self.state.busy
        self.pull_btn.setEnabled(ok)
        self.first_pull.setEnabled(ok)
        self.push_btn.setEnabled(ok and bool(self.segs))
        for name in ("Export…", "GPX…", "Rename…", "Delete"):
            self.btns[name].setEnabled(bool(s))
        self.btns["Import…"].setEnabled(bool(v))
        self.share_btn.setEnabled(len(sel) == 1)
        self.clip_btn.setEnabled(len(sel) == 1 and bool(track.clip(self.recordings(), sel[0].get("mark"))))

    # ---- the phone ----

    def _job(self, what, fn, done):
        try:
            target = self.state.target()
        except SystemExit as e:
            forms.error(self, "Track", str(e.code))
            return
        if not self.state.begin(what):
            return
        self.note.setText(what[0].upper() + what[1:] + "…")

        def ok(r):
            self.state.end()
            done(r)

        def failed(msg):
            self.state.end()
            self.note.setText("")
            forms.error(self, "Track", msg)
        worker.run(lambda: fn(target), ok, failed)

    def sync_to_pc(self):
        v = self.vehicle()

        def done(r):
            self.note.setText("Copied %d segment%s and %d run%s from the phone." % (
                r["segments"], "" if r["segments"] == 1 else "s", r["runs"], "" if r["runs"] == 1 else "s")
                if r["segments"] or r["runs"] else "Nothing new on the phone.")
            self.load(self._sid())
        self._job("copying track segments and runs", lambda t: track.sync_to_pc(t, v), done)

    def sync_to_card(self):
        v = self.vehicle()

        def done(r):
            self.note.setText("On the card: %d segments. %s" % (r["segments"], "The app " + r["app"] + "." if r["app"]
                                                                else "Nothing new." if not r["copied"] else
                                                                "The app takes them in when it next shows Track."))
        self._job("putting segments on the card", lambda t: track.sync_to_card(t, v), done)

    # ---- segments ----

    def import_segment(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import a segment", "", "Segments (*.json *.gpx)")
        if not path:
            return
        try:
            sid = track.import_segment(self.vehicle(), path)
        except (OSError, ValueError) as e:
            forms.error(self, "Import", str(e))
            return
        self.load(sid)
        self.note.setText("Imported. Sync to card puts it on the phone.")

    def export_segment(self):
        s = self._seg()
        path, _ = QFileDialog.getSaveFileName(self, "Export the segment", s["name"] + ".segment.json",
                                              "Segment (*.segment.json)")
        if path:
            track.export_segment(self.vehicle(), s["id"], path)
            self.note.setText("Saved %s; whoever gets it adds it with Import." % os.path.basename(path))

    def export_gpx(self):
        s = self._seg()
        path, _ = QFileDialog.getSaveFileName(self, "The segment as GPX", s["name"] + ".gpx", "GPX (*.gpx)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(track.segment_gpx(s))

    def rename(self):
        s = self._seg()
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=s["name"])
        if ok and name.strip() and name.strip() != s["name"]:
            try:
                track.rename(self.vehicle(), s["id"], name)
                track.mark_renamed(self.vehicle(), s["id"])
            except (OSError, ValueError) as e:
                forms.error(self, "Rename", str(e))
            self.load(s["id"])
            self.note.setText("Renamed. Sync to card puts the new name on the phone.")

    def delete(self):
        s = self._seg()
        if QMessageBox.question(self, "Delete", "Take %s and its %d runs off this computer? The phone keeps it until "
                                "you delete it there (Track page)." % (s["name"], s["runs"])) == QMessageBox.Yes:
            track.delete(self.vehicle(), s["id"])
            self.load()

    # ---- runs ----

    def share_run(self):
        s, r = self._seg(), self._selected_runs()[0]
        dest = QFileDialog.getExistingDirectory(self, "Where should the run's folder go?", os.path.expanduser("~/Desktop"))
        if not dest:
            return
        try:
            folder, has_clip = track.share_run(self.vehicle(), s["id"], r["file"], dest, self.recordings())
        except (OSError, ValueError) as e:
            forms.error(self, "Share run", str(e))
            return
        self.note.setText(("Made %s with the clip, GPX and CSV." if has_clip else
                           "Made %s with the GPX and CSV. No clip: " + ("its mark is not copied to this computer yet "
                                                                        "(Recordings: Sync to PC)." if r.get("mark") else
                                                                        "the dashcam was not recording.")) % os.path.basename(folder))
        forms.show_folder(folder)

    def show_clip(self):
        r = self._selected_runs()[0]
        c = track.clip(self.recordings(), r.get("mark"))
        if c:
            forms.show_folder(os.path.dirname(c))
