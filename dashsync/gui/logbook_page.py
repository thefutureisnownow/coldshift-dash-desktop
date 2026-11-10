"""Log book page: the vehicle's trips, fill-ups, odometer readings and services (dashsync/logbook.py). Copy
them from the phone, add or correct entries here, see fuel use and monthly figures, set service reminders
(the phone shows them when due), and make the SARS travel logbook for a tax year as a PDF or CSV."""
import datetime

from PySide6.QtCore import QDateTime, QMarginsF, QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import (QColor, QDesktopServices, QPainter, QPageLayout, QPageSize, QPainterPath, QPdfWriter, QPen,
                           QTextDocument)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .. import logbook, paths, recordings, tripfiles
from . import forms, worker
from .recordings_page import recordings_dest

EID = Qt.UserRole
FILTERS = [("All", None), ("Trips", "trip"), ("Business trips", "business"), ("Fill-ups", "fuel"),
           ("Odometer readings", "odometer"), ("Services", "service")]
SERVICES = ["Service", "Oil change", "Tyres", "Brakes", "Battery", "Licence renewal", "Roadworthy", "Wash"]
NAMES = {"trip": "Trip", "fuel": "Fill-up", "odometer": "Odometer", "service": "Service", "reminder": "Reminder"}


def money(v):
    return "" if v is None else "R {:,.2f}".format(v).replace(",", " ")


def km(v, digits=0):
    return "" if v is None else ("{:,.%df} km" % digits).format(v).replace(",", " ")


def when(ms, fmt="%a %d %b %Y  %H:%M"):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime(fmt)


def _number(edit):
    t = edit.text().strip().replace(",", ".").replace(" ", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        raise ValueError("%r is not a number" % edit.text())


class EntryDialog(QDialog):
    """Adds or edits one entry; the fields depend on its type."""
    def __init__(self, parent, entry, es):
        super().__init__(parent)
        self.entry, self.es = dict(entry), es
        t = entry["type"]
        self.setWindowTitle(("Edit " if "updated" in entry else "Add ") + NAMES[t].lower())
        f = forms.form()
        self.time = self._time(entry["time"])
        f.addRow("When" if t != "trip" else "Started", self.time)
        guess = logbook.odometer_at(es, entry["time"])
        self.odo = QLineEdit(self._text(entry.get("odometer")))
        self.odo.setPlaceholderText("about %.0f" % guess if guess else "km on the dashboard")
        if t == "fuel":
            self.litres = QLineEdit(self._text(entry.get("litres")))
            self.price = QLineEdit(self._text(entry.get("price")))
            self.total = QLineEdit(self._text(entry.get("total")))
            for w, tip in ((self.litres, "L"), (self.price, "R per litre"), (self.total, "R")):
                w.setPlaceholderText(tip)
            self.grade = QComboBox()
            self.grade.setEditable(True)
            self.grade.addItems(logbook.GRADES)
            self.grade.setCurrentText(entry.get("grade", logbook.GRADES[0]))
            self.full = QCheckBox("Filled to full")
            self.full.setChecked(entry.get("full", True))
            self.missed = QCheckBox("A fill-up before this one was not logged")
            self.missed.setChecked(bool(entry.get("missed")))
            self.station = QLineEdit(entry.get("station", ""))
            f.addRow("Litres", self.litres)
            f.addRow("Price per litre", self.price)
            f.addRow("Total", self.total)
            f.addRow("", forms.note("Fill in any two of the three."))
            f.addRow("Odometer", self.odo)
            f.addRow("Fuel", self.grade)
            f.addRow("", self.full)
            f.addRow("", self.missed)
            f.addRow("Station", self.station)
        elif t == "odometer":
            f.addRow("Odometer", self.odo)
        elif t == "service":
            self.what = QComboBox()
            self.what.setEditable(True)
            self.what.addItems(SERVICES)
            self.what.setCurrentText(entry.get("what", ""))
            self.cost = QLineEdit(self._text(entry.get("cost")))
            self.cost.setPlaceholderText("R")
            f.addRow("What", self.what)
            f.addRow("Cost", self.cost)
            f.addRow("Odometer", self.odo)
        else:
            self.end = self._time(entry.get("end", entry["time"] + 1800000))
            k = logbook.factor(es)
            self.dist = QLineEdit("%.1f" % logbook.trip_km(entry, k) if entry.get("dist_m") else "")
            self.dist.setPlaceholderText("km")
            self.k = k
            self.frm = QLineEdit((entry.get("from") or {}).get("name", ""))
            self.to = QLineEdit((entry.get("to") or {}).get("name", ""))
            self.business = QCheckBox("Business trip")
            self.business.setChecked(bool(entry.get("business")))
            self.purpose = QLineEdit(entry.get("purpose", ""))
            self.purpose.setPlaceholderText("Where to and why, for example: Client visit, Acme in George")
            f.addRow("Ended", self.end)
            f.addRow("Distance", self.dist)
            f.addRow("From", self.frm)
            f.addRow("To", self.to)
            f.addRow("", self.business)
            f.addRow("Purpose", self.purpose)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addLayout(f)
        v.addWidget(buttons)
        self.setMinimumWidth(460)

    @staticmethod
    def _text(v):
        return "" if v is None else ("%d" % v if float(v) == int(v) else "%g" % v)

    @staticmethod
    def _time(ms):
        w = QDateTimeEdit(QDateTime.fromMSecsSinceEpoch(int(ms)))
        w.setCalendarPopup(True)
        w.setDisplayFormat("ddd d MMM yyyy  HH:mm")
        return w

    def save(self):
        e, t = self.entry, self.entry["type"]
        try:
            e["time"] = self.time.dateTime().toMSecsSinceEpoch()
            odo = _number(self.odo)
            if odo:
                e["odometer"] = round(odo)
            else:
                e.pop("odometer", None)
            if t == "fuel":
                litres, price, total = logbook.work_out(_number(self.litres), _number(self.price), _number(self.total))
                e.update({"litres": litres, "price": price, "total": total, "grade": self.grade.currentText().strip(),
                          "full": self.full.isChecked(), "missed": self.missed.isChecked(),
                          "station": self.station.text().strip()})
            elif t == "service":
                e["what"] = self.what.currentText().strip()
                cost = _number(self.cost)
                if cost is None:
                    e.pop("cost", None)
                else:
                    e["cost"] = cost
            elif t == "trip":
                e["end"] = self.end.dateTime().toMSecsSinceEpoch()
                d = _number(self.dist)
                # distances are kept as GPS metres, which the odometer factor scales
                e["dist_m"] = round(d * 1000 / self.k) if d else 0
                e["from"] = dict(e.get("from") or {}, name=self.frm.text().strip())
                e["to"] = dict(e.get("to") or {}, name=self.to.text().strip())
                e["business"] = self.business.isChecked()
                e["purpose"] = self.purpose.text().strip()
            logbook.check(e)
        except ValueError as ex:
            forms.error(self, "Save", str(ex))
            return
        self.accept()


class ReminderDialog(QDialog):
    """Adds or edits a service reminder: what, how often (km, months or both), and when it was last done."""
    def __init__(self, parent, entry, es):
        super().__init__(parent)
        self.entry, self.es = dict(entry), es
        self.setWindowTitle(("Edit" if "updated" in entry else "Add") + " service reminder")
        f = forms.form()
        self.what = QComboBox()
        self.what.setEditable(True)
        self.what.addItems([p[0] for p in logbook.PRESETS])
        self.what.setCurrentText(entry.get("what", ""))
        self.what.activated.connect(self._preset)
        self.km = QLineEdit(EntryDialog._text(entry.get("every_km") or None))
        self.km.setPlaceholderText("km (empty: not by distance)")
        self.months = QLineEdit(EntryDialog._text(entry.get("every_months") or None))
        self.months.setPlaceholderText("months (empty: not by time)")
        self.time = EntryDialog._time(entry["time"])
        guess = logbook.odometer_at(es, entry["time"])
        self.odo = QLineEdit(EntryDialog._text(entry.get("from_odometer")))
        self.odo.setPlaceholderText("about %.0f" % guess if guess else "km when it was last done")
        f.addRow("What", self.what)
        f.addRow("Every", self.km)
        f.addRow("or every", self.months)
        f.addRow("Last done", self.time)
        f.addRow("at", self.odo)
        f.addRow("", forms.note("A service logged with the same name (on the phone or here) starts it again."))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addLayout(f)
        v.addWidget(buttons)
        self.setMinimumWidth(460)
        if not entry.get("what"):
            self._preset(0)

    def _preset(self, i):
        name, km_, months = logbook.PRESETS[i]
        self.what.setCurrentText(name)
        self.km.setText(str(km_) if km_ else "")
        self.months.setText(str(months) if months else "")

    def save(self):
        e = self.entry
        try:
            e["what"] = self.what.currentText().strip()
            e["every_km"] = round(_number(self.km) or 0)
            e["every_months"] = round(_number(self.months) or 0)
            e["time"] = self.time.dateTime().toMSecsSinceEpoch()
            odo = _number(self.odo)
            if odo:
                e["from_odometer"] = round(odo)
            else:
                e.pop("from_odometer", None)
            logbook.check(e)
        except ValueError as ex:
            forms.error(self, "Save", str(ex))
            return
        self.accept()


class FuelChart(QWidget):
    """Fuel use per full tank over time (L/100 km), with the average as a line."""
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(180)
        self.points, self.avg = [], None

    def show_points(self, points, avg):
        self.points, self.avg = points, avg
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        text = self.palette().windowText().color()
        dim = self.palette().placeholderText().color()
        r = QRectF(48, 14, self.width() - 64, self.height() - 40)
        if len(self.points) < 1:
            p.setPen(dim)
            p.drawText(self.rect(), Qt.AlignCenter, "Fuel use appears after two full tanks with odometer readings.")
            return
        ys = [v for _, v, _ in self.points]
        lo, hi = min(ys + [self.avg or ys[0]]), max(ys + [self.avg or ys[0]])
        lo, hi = lo - 0.5, hi + 0.5
        t0, t1 = self.points[0][0], self.points[-1][0]
        x = lambda t: r.left() + (r.width() * (t - t0) / (t1 - t0) if t1 > t0 else r.width() / 2)
        y = lambda v: r.bottom() - r.height() * (v - lo) / (hi - lo)
        p.setPen(QPen(dim, 1))
        for v in (lo + 0.5, (lo + hi) / 2, hi - 0.5):
            p.drawText(QRectF(0, y(v) - 8, 44, 16), Qt.AlignRight | Qt.AlignVCenter, "%.1f" % v)
        p.drawText(QRectF(r.left(), r.bottom() + 6, r.width(), 18), Qt.AlignLeft, when(t0, "%d %b %Y"))
        p.drawText(QRectF(r.left(), r.bottom() + 6, r.width(), 18), Qt.AlignRight, when(t1, "%d %b %Y"))
        p.drawText(QRectF(r.left(), 0, r.width(), 14), Qt.AlignCenter, "L/100 km per full tank")
        if self.avg:
            p.setPen(QPen(dim, 1, Qt.DashLine))
            p.drawLine(QPointF(r.left(), y(self.avg)), QPointF(r.right(), y(self.avg)))
        path = QPainterPath(QPointF(x(self.points[0][0]), y(self.points[0][1])))
        for t, v, _ in self.points[1:]:
            path.lineTo(x(t), y(v))
        p.setPen(QPen(QColor("#2f7bff"), 2))
        p.drawPath(path)
        p.setBrush(QColor("#2f7bff"))
        for t, v, _ in self.points:
            p.drawEllipse(QPointF(x(t), y(v)), 3.5, 3.5)
        p.setPen(text)


class LogbookPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.es = []

        top = QHBoxLayout()
        self.pull_btn = QPushButton("Sync to PC")
        self.pull_btn.setToolTip("Copy the phone's trips, fill-ups and readings into this vehicle")
        self.pull_btn.clicked.connect(self.sync_to_pc)
        self.push_btn = QPushButton("Sync to card")
        self.push_btn.setToolTip("Put entries added or changed here on the phone")
        self.push_btn.clicked.connect(self.sync_to_card)
        self.note = QLabel()
        self.note.setWordWrap(True)
        top.addWidget(self.pull_btn)
        top.addWidget(self.push_btn)
        top.addWidget(self.note, 1)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-size: 15px")

        self.tabs = QTabWidget()
        self.tabs.addTab(self._entries_tab(), "Entries")
        self.tabs.addTab(self._months_tab(), "Months")
        self.tabs.addTab(self._reminders_tab(), "Reminders")
        self.tabs.addTab(self._sars_tab(), "SARS logbook")

        page = QVBoxLayout(self)
        page.addWidget(self.summary)
        page.addWidget(self.tabs, 1)
        page.addLayout(top)
        state.busy_changed.connect(self._buttons)
        state.target_changed.connect(self._buttons)
        self.load()

    # ---- building ----

    @staticmethod
    def _table(headers, stretch):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        hh = t.horizontalHeader()
        for c in range(len(headers)):
            hh.setSectionResizeMode(c, QHeaderView.Stretch if c == stretch else QHeaderView.ResizeToContents)
        t.verticalHeader().hide()
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        return t

    def _entries_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.filter = QComboBox()
        for name, _ in FILTERS:
            self.filter.addItem(name)
        self.filter.currentIndexChanged.connect(self._fill_entries)
        bar.addWidget(QLabel("Show"))
        bar.addWidget(self.filter)
        bar.addStretch()
        self.add_btns = []
        for text, kind in (("Add fill-up…", "fuel"), ("Add reading…", "odometer"), ("Add service…", "service"),
                           ("Add trip…", "trip")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=kind: self.add(k))
            bar.addWidget(b)
            self.add_btns.append(b)
        v.addLayout(bar)
        self.table = self._table(["When", "What", "Details", "Distance", "Odometer", "Amount", "Purpose"], 2)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._buttons)
        self.table.itemDoubleClicked.connect(self.edit)
        v.addWidget(self.table, 1)
        low = QHBoxLayout()
        self.edit_btn = QPushButton("Edit…")
        self.edit_btn.clicked.connect(self.edit)
        self.biz_btn = QPushButton("Business")
        self.biz_btn.setToolTip("Mark the selected trips as business trips")
        self.biz_btn.clicked.connect(lambda: self.set_business(True))
        self.priv_btn = QPushButton("Private")
        self.priv_btn.clicked.connect(lambda: self.set_business(False))
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self.delete)
        self.csv_btn = QPushButton("Export CSV…")
        self.csv_btn.setToolTip("Every entry, for a spreadsheet")
        self.csv_btn.clicked.connect(self.export_csv)
        self.gpx_btn = QPushButton("Export GPX…")
        self.gpx_btn.setToolTip("The routes of the selected trips (or of the trips shown), for maps and other tools")
        self.gpx_btn.clicked.connect(self.export_gpx)
        self.gather_btn = QPushButton("Gather trip files…")
        self.gather_btn.setToolTip("Copies everything recorded during the selected trip (clips, marks, sound, interior "
                                   "shots, the route) into a folder of its own, copying new recordings off the phone first")
        self.gather_btn.clicked.connect(self.gather_trip)
        for b in (self.edit_btn, self.biz_btn, self.priv_btn, self.del_btn):
            low.addWidget(b)
        low.addStretch()
        low.addWidget(self.gather_btn)
        low.addWidget(self.gpx_btn)
        low.addWidget(self.csv_btn)
        v.addLayout(low)
        return w

    def _months_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.chart = FuelChart()
        v.addWidget(self.chart)
        self.months = self._table(["Month", "Driven", "Business", "Fill-ups", "Litres", "Fuel", "L/100 km",
                                   "Fuel per km", "Services"], 0)
        v.addWidget(self.months, 1)
        return w

    def _reminders_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(forms.note("The phone heads its log with a reminder from %d km or %d days before it is due. "
                               "Logging a service of the same name starts it again." % (logbook.SOON_KM,
                                                                                        logbook.SOON_DAYS)))
        self.rem_table = self._table(["What", "Every", "Last done", "Next due", "Left"], 0)
        self.rem_table.itemSelectionChanged.connect(self._buttons)
        self.rem_table.itemDoubleClicked.connect(self.edit_reminder)
        v.addWidget(self.rem_table, 1)
        low = QHBoxLayout()
        self.rem_add = QPushButton("Add reminder…")
        self.rem_add.clicked.connect(self.add_reminder)
        self.rem_edit = QPushButton("Edit…")
        self.rem_edit.clicked.connect(self.edit_reminder)
        self.rem_done = QPushButton("Done today…")
        self.rem_done.setToolTip("Log the service now (it starts the reminder again)")
        self.rem_done.clicked.connect(self.reminder_done)
        self.rem_del = QPushButton("Delete")
        self.rem_del.clicked.connect(self.delete_reminder)
        for b in (self.rem_add, self.rem_edit, self.rem_done, self.rem_del):
            low.addWidget(b)
        low.addStretch()
        v.addLayout(low)
        return w

    def _sars_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        f = forms.form()
        self.year = QComboBox()
        self.year.currentIndexChanged.connect(self._fill_sars)
        self.vehicle_text = QLineEdit()
        self.vehicle_text.setPlaceholderText("Make, model and registration, for example: Toyota Corolla 1.6, CA 123-456")
        self.vehicle_text.editingFinished.connect(self._save_vehicle_text)
        f.addRow("Year of assessment", self.year)
        f.addRow("Vehicle", self.vehicle_text)
        v.addLayout(f)
        self.sars_facts = QLabel()
        self.sars_facts.setWordWrap(True)
        self.sars_facts.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.sars_facts)
        self.sars_warn = QLabel()
        self.sars_warn.setWordWrap(True)
        self.sars_warn.setStyleSheet("color: %s" % forms.WARN)
        v.addWidget(self.sars_warn)
        self.sars_table = self._table(["Date", "Opening km", "Closing km", "Business km", "Trip", "Where to and why"], 5)
        v.addWidget(self.sars_table, 1)
        low = QHBoxLayout()
        self.pdf_btn = QPushButton("Save PDF…")
        self.pdf_btn.clicked.connect(self.save_pdf)
        self.sars_csv_btn = QPushButton("Save CSV…")
        self.sars_csv_btn.clicked.connect(self.save_sars_csv)
        low.addWidget(forms.note("SARS asks for the odometer at the start and end of the year and, for each "
                                 "business trip, the date, distance and where to and why. Mark trips as business "
                                 "on the phone or here (Entries)."), 1)
        low.addWidget(self.pdf_btn)
        low.addWidget(self.sars_csv_btn)
        v.addLayout(low)
        return w

    # ---- showing ----

    def vehicle(self):
        return paths.load_config().get("workspace")

    def showEvent(self, e):
        super().showEvent(e)
        self.load()

    def load(self):
        v = self.vehicle()
        self.es = logbook.entries(v) if v else []
        k = logbook.factor(self.es)
        odo = logbook.odometer_at(self.es, logbook.now_ms(), k)
        c = logbook.consumption(self.es)
        avg = logbook.average_l100(self.es)
        parts = ["Odometer about <b>%s</b>" % km(odo) if odo else "No odometer reading yet",
                 "fuel use <b>%.1f</b> L/100 km last tank, <b>%.1f</b> average" % (c[-1][1], avg) if c else
                 "fuel use shows after two full tanks",
                 "GPS distances × %.3f to match the odometer" % k if k != 1.0 else "GPS distances not yet matched to the odometer"]
        due = [d for d in logbook.reminders(self.es) if d["soon"]]
        if due:
            parts.append("<span style='color: %s'>%s</span>" % (
                forms.WARN, ", ".join("%s %s" % (d["what"], logbook.due_text(d)) for d in due)))
        self.summary.setText(" · ".join(parts))
        self._fill_entries()
        self._fill_months(c, avg)
        self._fill_reminders()
        self._fill_years()
        self.vehicle_text.setText(logbook.vehicle_text(v) if v else "")
        if not self.es:
            self.note.setText("No entries yet: trips log themselves on the phone (Log book page); Sync to PC copies them here.")
        self._buttons()

    def _shown(self):
        kind = FILTERS[self.filter.currentIndex()][1]
        if kind == "business":
            return [e for e in self.es if e["type"] == "trip" and e.get("business")]
        return [e for e in self.es if (kind is None and e["type"] != "reminder") or e["type"] == kind]

    def _fill_entries(self):
        k = logbook.factor(self.es)
        rows = self._shown()
        self.table.setRowCount(len(rows))
        for i, e in enumerate(rows):
            t = e["type"]
            dist = odo = amount = purpose = ""
            if t == "trip":
                what = "Business trip" if e.get("business") else "Trip"
                details = "%s → %s · %d min" % ((e.get("from") or {}).get("name", "") or "…",
                                                (e.get("to") or {}).get("name", "") or "…",
                                                max(1, (e.get("end", e["time"]) - e["time"]) // 60000))
                dist = km(logbook.trip_km(e, k), 1)
                purpose = e.get("purpose", "") if e.get("business") else ""
            elif t == "fuel":
                what = "Fill-up"
                details = "%.2f L at %s · %s%s%s" % (e.get("litres", 0), money(e.get("price")), e.get("grade", ""),
                                                     "" if e.get("full", True) else " · part fill",
                                                     " · " + e["station"] if e.get("station") else "")
                amount = money(e.get("total"))
            elif t == "service":
                what, details, amount = "Service", e.get("what", ""), money(e.get("cost"))
            else:
                what, details = "Odometer reading", ""
            if e.get("odometer"):
                odo = km(e["odometer"])
            for c, text in enumerate([when(e["time"]), what, details, dist, odo, amount, purpose]):
                it = QTableWidgetItem(text)
                it.setData(EID, e["id"])
                if c in (3, 4, 5):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, c, it)
        self._buttons()

    def _fill_months(self, c, avg):
        self.chart.show_points(c, avg)
        rows = logbook.months(self.es)
        self.months.setRowCount(len(rows))
        for i, r in enumerate(rows):
            label = datetime.datetime.strptime(r["month"], "%Y-%m").strftime("%B %Y")
            cells = [label, km(r["km"]), km(r["business_km"]), str(r["fills"]) if r["fills"] else "",
                     "%.1f L" % r["litres"] if r["litres"] else "", money(r["fuel_cost"]) if r["fuel_cost"] else "",
                     "%.1f" % r["l100"] if r["l100"] else "",
                     money(r["cost_per_km"]) if r["cost_per_km"] and r["fuel_cost"] else "",
                     money(r["service_cost"]) if r["service_cost"] else ""]
            for col, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if col:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.months.setItem(i, col, it)

    def _fill_reminders(self):
        self.rems = logbook.reminders(self.es)
        self.rem_table.setRowCount(len(self.rems))
        for i, d in enumerate(self.rems):
            r = d["entry"]
            every = " or ".join(x for x in (km(r.get("every_km")) if r.get("every_km") else "",
                                            "%d months" % r["every_months"] if r.get("every_months") else "") if x)
            last = when(d["last_time"], "%d %b %Y") + (" at " + km(d["last_odo"]) if d["last_odo"] and r.get("every_km") else "")
            nxt = " or ".join(x for x in (km(d["due_odo"]) if d["due_odo"] else "",
                                          when(d["due_time"], "%d %b %Y") if d["due_time"] else "") if x)
            cells = [d["what"], every, last, nxt, logbook.due_text(d)]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setData(EID, r["id"])
                if c == 4 and d["soon"]:
                    it.setForeground(QColor(forms.WARN if d["overdue"] else "#c9952a"))
                self.rem_table.setItem(i, c, it)

    def _reminder(self):
        rows = self.rem_table.selectionModel().selectedRows() if hasattr(self, "rem_table") else []
        if not rows:
            return None
        eid = self.rem_table.item(rows[0].row(), 0).data(EID)
        return next((d for d in self.rems if d["entry"]["id"] == eid), None)

    def add_reminder(self):
        self._reminder_dialog(logbook.make("reminder", logbook.now_ms()))

    def edit_reminder(self, *_):
        d = self._reminder()
        if d:
            self._reminder_dialog(d["entry"])

    def _reminder_dialog(self, entry):
        dlg = ReminderDialog(self, entry, self.es)
        try:
            if dlg.exec() != QDialog.Accepted:
                return
            logbook.put(self.vehicle(), dlg.entry)
        except (OSError, ValueError) as ex:
            forms.error(self, "Save", str(ex))
        finally:
            dlg.deleteLater()
        self.note.setText("Saved here. Sync to card puts it on the phone.")
        self.load()

    def reminder_done(self):
        d = self._reminder()
        if d:
            e = logbook.make("service", logbook.now_ms())
            e["what"] = d["what"]
            self._edit_dialog(e)

    def delete_reminder(self):
        d = self._reminder()
        if d and QMessageBox.question(self, "Delete", "Delete the reminder for %s?" % d["what"]) == QMessageBox.Yes:
            logbook.delete(self.vehicle(), d["entry"]["id"])
            self.load()

    def _fill_years(self):
        keep = self.year.currentData()
        years = {logbook.current_tax_year()}
        for e in self.es:
            d = datetime.datetime.fromtimestamp(e["time"] / 1000)
            years.add(logbook.current_tax_year(d.date()))
        self.year.blockSignals(True)
        self.year.clear()
        for y in sorted(years, reverse=True):
            self.year.addItem("1 March %d – 28/29 February %d" % (y - 1, y), y)
        i = self.year.findData(keep)
        self.year.setCurrentIndex(i if i >= 0 else 0)
        self.year.blockSignals(False)
        self._fill_sars()

    def _report(self):
        y = self.year.currentData()
        return logbook.sars(self.es, y) if y else None

    def _fill_sars(self, *_):
        r = self._report()
        if not r:
            return
        self.sars_facts.setText(
            "Opening odometer <b>%s</b> · closing <b>%s</b> · total <b>%s</b> · business <b>%s</b> (%d trips) · "
            "private <b>%s</b>" % (km(r["opening"]) or "unknown", km(r["closing"]) or "unknown", km(r["total_km"]),
                                   km(r["business_km"]), len(r["trips"]), km(r["private_km"])))
        self.sars_facts.setText(self.sars_facts.text().replace("(1 trips)", "(1 trip)"))
        warn = []
        if r["no_purpose"]:
            warn.append("%d business trip%s without a purpose (where to and why)." % (
                r["no_purpose"], "" if r["no_purpose"] == 1 else "s"))
        if r["opening"] is None:
            warn.append("No odometer reading: add one (Add reading…) so the logbook has opening and closing readings.")
        elif not r["readings"]:
            warn.append("No odometer reading in this year: the opening and closing readings are estimates from GPS. "
                        "Add the readings from the start and end of the year if you have them.")
        self.sars_warn.setText(" ".join(warn))
        self.sars_warn.setVisible(bool(warn))
        self.sars_table.setRowCount(len(r["trips"]))
        for i, t in enumerate(r["trips"]):
            cells = [t["date"], km(t["odo_start"]), km(t["odo_end"]), "%.1f" % t["km"],
                     "%s → %s" % (t["from"] or "…", t["to"] or "…"), t["purpose"]]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c in (1, 2, 3):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.sars_table.setItem(i, c, it)
        self._buttons()

    def _selected(self):
        ids = {self.table.item(i.row(), 0).data(EID) for i in self.table.selectionModel().selectedRows()}
        return [e for e in self.es if e["id"] in ids]

    def _buttons(self):
        v = self.vehicle()
        ok = bool(v) and self.state.has_target() and not self.state.busy
        sel = self._selected()
        trips = [e for e in sel if e["type"] == "trip"]
        self.pull_btn.setEnabled(ok)
        self.push_btn.setEnabled(ok)
        for b in self.add_btns:
            b.setEnabled(bool(v))
        self.edit_btn.setEnabled(len(sel) == 1)
        self.biz_btn.setEnabled(bool(trips) and len(trips) == len(sel))
        self.priv_btn.setEnabled(bool(trips) and len(trips) == len(sel))
        self.del_btn.setEnabled(bool(sel))
        self.csv_btn.setEnabled(bool(self.es))
        self.gpx_btn.setEnabled(any(e["type"] == "trip" for e in (sel or self._shown())))
        self.gather_btn.setEnabled(len(sel) == 1 and len(trips) == 1 and bool(recordings_dest()) and not self.state.busy)
        rem = self._reminder()
        self.rem_add.setEnabled(bool(v))
        for b in (self.rem_edit, self.rem_done, self.rem_del):
            b.setEnabled(rem is not None)
        has = bool(self.es)
        self.pdf_btn.setEnabled(has)
        self.sars_csv_btn.setEnabled(has)

    # ---- editing ----

    def _edit_dialog(self, entry):
        d = EntryDialog(self, entry, self.es)
        try:
            if d.exec() != QDialog.Accepted:
                return
            logbook.put(self.vehicle(), d.entry)
        except (OSError, ValueError) as ex:
            forms.error(self, "Save", str(ex))
        finally:
            d.deleteLater()
        self.note.setText("Saved here. Sync to card puts it on the phone.")
        self.load()

    def add(self, kind):
        e = logbook.make(kind, logbook.now_ms())
        if kind == "trip":
            e["time"] -= 1800000
            e["end"] = logbook.now_ms()
        self._edit_dialog(e)

    def edit(self, *_):
        sel = self._selected()
        if len(sel) == 1:
            self._edit_dialog(sel[0])

    def set_business(self, on):
        trips = [e for e in self._selected() if e["type"] == "trip"]
        purpose = None
        if on and any(not e.get("purpose") for e in trips):
            used = sorted({e["purpose"] for e in self.es if e.get("purpose")})
            text, ok = QInputDialog.getItem(self, "Business trips", "Where to and why (for the trips without one):",
                                            used or [""], 0, True)
            if not ok:
                return
            purpose = text.strip()
        for e in trips:
            e = dict(e, business=on)
            if purpose and not e.get("purpose"):
                e["purpose"] = purpose
            logbook.put(self.vehicle(), e)
        self.note.setText("Changed %d trip%s here. Sync to card puts %s on the phone." % (
            len(trips), "" if len(trips) == 1 else "s", "it" if len(trips) == 1 else "them"))
        self.load()

    def delete(self):
        sel = self._selected()
        if not sel or QMessageBox.question(self, "Delete", "Delete %d entr%s? The phone's copies go too with the "
                                           "next Sync to card." % (len(sel), "y" if len(sel) == 1 else "ies")) \
                != QMessageBox.Yes:
            return
        for e in sel:
            logbook.delete(self.vehicle(), e["id"])
        self.load()

    def _save_vehicle_text(self):
        v = self.vehicle()
        if v and self.vehicle_text.text().strip() != logbook.vehicle_text(v):
            logbook.set_vehicle_text(v, self.vehicle_text.text())

    # ---- files ----

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export the log book", "logbook.csv", "CSV (*.csv)")
        if path:
            logbook.export_csv(self.es, path)
            self.note.setText("Saved %s." % path)

    def export_gpx(self):
        trips = [e for e in (self._selected() or self._shown()) if e["type"] == "trip"]
        path, _ = QFileDialog.getSaveFileName(self, "Export trips as GPX", "trips.gpx", "GPX (*.gpx)")
        if not path:
            return
        n = logbook.export_gpx(self.vehicle(), trips, path)
        self.note.setText("Saved %d trip%s in %s." % (n, "" if n == 1 else "s", path) if n else
                          "None of those trips has a route: trips added by hand, or logged before the app kept "
                          "routes, have none. Sync to PC copies the phone's.")

    def save_sars_csv(self):
        r = self._report()
        path, _ = QFileDialog.getSaveFileName(self, "Save the travel logbook", "travel-logbook-%d.csv" % r["year"],
                                              "CSV (*.csv)")
        if path:
            self._save_vehicle_text()
            logbook.sars_csv(r, path, self.vehicle_text.text().strip())
            self.note.setText("Saved %s." % path)

    def save_pdf(self):
        r = self._report()
        path, _ = QFileDialog.getSaveFileName(self, "Save the travel logbook", "travel-logbook-%d.pdf" % r["year"],
                                              "PDF (*.pdf)")
        if path:
            self._save_vehicle_text()
            write_pdf(logbook.sars_html(r, self.vehicle_text.text().strip()), path)
            self.note.setText("Saved %s." % path)

    # ---- the phone ----

    def _job(self, what, fn, done):
        try:
            target = self.state.target()
        except SystemExit as e:
            forms.error(self, "Log book", str(e.code))
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
            forms.error(self, "Log book", msg)
        worker.run(lambda: fn(target), ok, failed)

    def gather_trip(self):
        """The selected trip's files into a folder: new recordings off the phone first (when one is connected), then
        what overlaps the trip, from the Recordings tab's copy."""
        trips = [e for e in self._selected() if e["type"] == "trip"]
        dest = recordings_dest()
        if len(trips) != 1 or not dest:
            return
        trip, v = trips[0], self.vehicle()
        sources = []
        if self.state.has_target():
            try:
                sources = self.state.sources()
            except SystemExit:
                sources = []                    # the phone is not reachable: gather what is here
        if not self.state.begin("gathering the trip's files"):
            return
        self.note.setText("Copying new recordings off the phone…" if sources else "Gathering the trip's files…")

        def work():
            if sources:
                recordings.pull(sources, dest, log=lambda s: None)
            return tripfiles.gather(v, dest, trip, log=lambda s: None)

        def ok(r):
            self.state.end()
            n = len(r["recordings"])
            self.note.setText("%d recording%s for this trip in %s (%d file%s copied%s)%s." % (
                n, "" if n == 1 else "s", r["folder"], r["copied"], "" if r["copied"] == 1 else "s",
                ", %d there already" % r["had"] if r["had"] else "",
                "" if r["route"] else "; no route was kept for it"))
            QDesktopServices.openUrl(QUrl.fromLocalFile(r["folder"]))

        def failed(msg):
            self.state.end()
            self.note.setText("")
            forms.error(self, "Log book", msg)
        worker.run(work, ok, failed)

    def sync_to_pc(self):
        v = self.vehicle()

        def done(r):
            n = r["new"] + r["updated"] + r["routes"]
            self.note.setText("Copied %d new and %d changed entr%s and %d route%s from the phone." % (
                r["new"], r["updated"], "y" if r["updated"] == 1 else "ies", r["routes"], "" if r["routes"] == 1 else "s")
                if n else "Nothing new on the phone.")
            self.load()
        self._job("copying the log book", lambda t: logbook.sync_to_pc(t, v), done)

    def sync_to_card(self):
        v = self.vehicle()

        def done(r):
            self.note.setText("Nothing added or changed here." if not r["entries"] else
                              "Sent %d entr%s; the app %s." % (r["entries"], "y" if r["entries"] == 1 else "ies",
                                                               r["app"] or "takes them in when it next shows the log book"))
        self._job("putting log book entries on the card", lambda t: logbook.sync_to_card(t, v), done)


def write_pdf(html, path):
    """An A4 PDF of a page of HTML."""
    w = QPdfWriter(path)
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(15, 15, 15, 15),
                                QPageLayout.Millimeter))
    w.setResolution(300)
    doc = QTextDocument()
    doc.setHtml(html)
    doc.print_(w)
