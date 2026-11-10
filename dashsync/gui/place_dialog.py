"""Adding a place on the computer: a name, its coordinates (pasted "lat, lon" works, as Google Maps
copies them) and whether it is a saved place, Home or Work. With the region's place search built (map
sync builds it), typing an address or a name finds it, the way the phone's Go to does."""
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QVBoxLayout)

from .. import places, search
from . import forms

HIT = Qt.UserRole


class PlaceDialog(QDialog):
    def __init__(self, parent, near=None):
        super().__init__(parent)
        self.setWindowTitle("Add a place")
        self.near = near                 # (lat, lon) to rank search results by, e.g. Home
        self.result = None
        lay = QVBoxLayout(self)
        self.db = None
        try:
            db = search.local_db()
            self.db = db if os.path.exists(db) else None
        except SystemExit:
            pass
        if self.db:
            self.find = QLineEdit()
            self.find.setPlaceholderText("Find: an address, a street or a place, e.g. 32 York Street, George")
            self.hits = QListWidget()
            self.hits.setMaximumHeight(170)
            self.hits.itemClicked.connect(self._pick)
            self.timer = QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(self._search)
            self.find.textChanged.connect(lambda *_: self.timer.start(150))
            lay.addWidget(self.find)
            lay.addWidget(self.hits)
        else:
            lay.addWidget(forms.note("Sync the map once (Maps tab) to search for places here by name or address."))
        self.name = QLineEdit()
        self.name.setPlaceholderText("As the phone lists it, e.g. Granny's")
        self.coords = QLineEdit()
        self.coords.setPlaceholderText("-33.92490, 18.42410")
        self.kind = QComboBox()
        for k, label in (("saved", "A saved place"), ("home", "Home"), ("work", "Work")):
            self.kind.addItem(label, k)
        f = forms.form()
        f.addRow("Name", self.name)
        f.addRow("Latitude, longitude", self.coords)
        f.addRow("Kind", self.kind)
        lay.addLayout(f)
        lay.addWidget(forms.note("Coordinates as Google Maps copies them work: right-click a spot there and click "
                                 "the numbers. Home and Work replace the phone's when synced to the card."))
        self.error = QLabel()
        self.error.setStyleSheet("color: %s" % forms.WARN)
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Add")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.sub = ""
        self.resize(560, 0)

    def _search(self):
        self.hits.clear()
        text = self.find.text().strip()
        if len(text) < 3:
            return
        lat, lon = self.near or (None, None)
        for r in search.query(self.db, text, lat, lon, limit=10):
            where = " · ".join(x for x in (r["detail"], r["area"]) if x)
            it = QListWidgetItem(r["name"] + ("  —  " + where if where else ""))
            it.setData(HIT, r)
            self.hits.addItem(it)
        if not self.hits.count():
            self.hits.addItem(QListWidgetItem("Nothing found"))

    def _pick(self, item):
        r = item.data(HIT)
        if not r:
            return
        self.name.setText(r["name"])
        self.coords.setText("%.6f, %.6f" % (r["lat"], r["lon"]))
        self.sub = " · ".join(x for x in (r["detail"], r["area"]) if x)

    def _accept(self):
        try:
            lat, lon = places.parse_coords(self.coords.text())
        except ValueError as e:
            self.error.setText(str(e)[0].upper() + str(e)[1:] + ".")
            return
        kind = self.kind.currentData()
        if not self.name.text().strip() and kind == "saved":
            self.error.setText("Give the place a name.")
            return
        self.result = (kind, self.name.text().strip(), lat, lon, self.sub)
        self.accept()
