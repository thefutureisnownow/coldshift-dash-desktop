"""Choosing the vehicle: shown when the window opens and from its Switch button. Everything the window
shows and keeps belongs to the open vehicle."""
import html
import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from .. import profile, vehicles
from . import forms

VID = Qt.UserRole


def car_icon(folder, size=72):
    src = profile.current_car(folder)
    pix = QPixmap(src) if src else QPixmap()
    return QIcon(pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)) if not pix.isNull() else QIcon()


class NewVehicleDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("New vehicle")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name, e.g. Peppermint Crisp")
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Folder (leave empty for the one below)")
        pick = QPushButton("Choose\u2026")
        pick.clicked.connect(self._pick)
        self.where = forms.note("")
        self.name.textChanged.connect(self._where)
        self.folder.textChanged.connect(self._where)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(pick)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("A vehicle keeps its own music, maps, voices, look and places, in its own folder."))
        lay.addWidget(self.name)
        lay.addLayout(row)
        lay.addWidget(self.where)
        lay.addWidget(buttons)
        self.resize(560, 0)
        self._where()

    def _where(self):
        f = self.folder.text().strip() or vehicles.default_folder(self.name.text().strip() or "vehicle")
        self.where.setText("Its files go in: " + f)

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, "Folder for the vehicle")
        if d:
            self.folder.setText(d)


class VehiclePicker(QDialog):
    """Pick, make, add, rename or forget vehicles; accepted with one open."""
    def __init__(self, parent=None, first=False):
        super().__init__(parent)
        self.setWindowTitle("coldshift.dash — vehicles")
        self.list = QListWidget()
        self.list.setIconSize(QSize(72, 72))
        self.list.setSpacing(4)
        # bound methods, not lambdas: a lambda holding the dialog keeps it alive through its own list,
        # and Qt then deletes the list twice when Python shuts down (a crash on quit)
        self.list.itemDoubleClicked.connect(self._double_clicked)
        self.list.currentItemChanged.connect(self._buttons)
        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(self.open_selected)
        new_btn = QPushButton("New vehicle\u2026")
        new_btn.clicked.connect(self.new_vehicle)
        (new_btn if first else self.open_btn).setDefault(True)
        cancel = QPushButton("Quit" if first else "Cancel")
        cancel.clicked.connect(self.reject)
        add_btn = QPushButton("Add a folder…")
        add_btn.setToolTip("A vehicle folder from another computer or a backup")
        add_btn.clicked.connect(self.add_folder)
        self.rename_btn = QPushButton("Rename…")
        self.rename_btn.clicked.connect(self.rename)
        self.forget_btn = QPushButton("Remove from list")
        self.forget_btn.setToolTip("Takes it off this list; its folder and files stay. (Not the open vehicle.)")
        self.forget_btn.clicked.connect(self.forget)
        side = QVBoxLayout()
        for b in (self.open_btn, new_btn, add_btn, self.rename_btn, self.forget_btn):
            side.addWidget(b)
        side.addStretch()
        side.addWidget(cancel)
        self.empty = forms.note("No vehicles yet. Press New vehicle\u2026 to start one, or Add a folder\u2026 to bring "
                                "in a vehicle from another computer or a backup.")
        body = QHBoxLayout()
        body.addWidget(self.list, 1)
        body.addLayout(side)
        lay = QVBoxLayout(self)
        intro = QLabel("Which vehicle? Everything here (music, maps, voices, look, places, its phone) is kept per vehicle."
                       if not first else "Start by making a vehicle. Everything here is kept per vehicle, in its own folder.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(body)
        lay.addWidget(self.empty)
        self.resize(760, 420)
        self.load()

    def load(self, select=None):
        self.list.clear()
        cur = vehicles.current()
        select = select or (cur["id"] if cur else None)
        grey = self.palette().color(QPalette.PlaceholderText).name()
        for v in vehicles.all():
            it = QListWidgetItem(car_icon(v["folder"]), "")
            it.setData(VID, v["id"])
            it.setToolTip(v["folder"])
            it.setSizeHint(QSize(0, 80))
            self.list.addItem(it)
            lab = QLabel("<b>%s</b>%s<br><span style='color:%s; font-size: 11px'>%s%s</span>" % (
                html.escape(v["name"]), " &nbsp;(open)" if cur and v["id"] == cur["id"] else "", grey,
                html.escape(self.fontMetrics().elidedText(v["folder"], Qt.ElideMiddle, 520)),
                " \u2014 folder missing" if not v["exists"] else ""))
            lab.setContentsMargins(8, 0, 0, 0)          # beside the icon the list already leaves room for
            self.list.setItemWidget(it, lab)
            if v["id"] == select:
                self.list.setCurrentItem(it)
        self.empty.setVisible(self.list.count() == 0)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._buttons()

    def _double_clicked(self, *_):
        self.open_selected()

    def _vid(self):
        it = self.list.currentItem()
        return it.data(VID) if it else None

    def _buttons(self, *_):
        vid = self._vid()
        cur = vehicles.current()
        for b in (self.open_btn, self.rename_btn):
            b.setEnabled(bool(vid))
        self.forget_btn.setEnabled(bool(vid) and not (cur and cur["id"] == vid))

    def open_selected(self):
        vid = self._vid()
        if not vid:
            return
        v = [x for x in vehicles.all() if x["id"] == vid][0]
        if not v["exists"]:
            forms.error(self, "Open", "the folder %s is missing (a disk not plugged in?)" % v["folder"])
            return
        vehicles.select(vid)
        self.accept()

    def new_vehicle(self):
        d = NewVehicleDialog(self)
        if d.exec() != QDialog.Accepted:
            return
        try:
            v = vehicles.create(d.name.text(), d.folder.text().strip() or None)
            profile.init(v["folder"])
        except (OSError, ValueError) as e:
            forms.error(self, "Vehicles", str(e))
            return
        self.load(v["id"])

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "A vehicle folder")
        if not d:
            return
        try:
            v = vehicles.add(d)
        except (OSError, ValueError) as e:
            forms.error(self, "Vehicles", str(e))
            return
        self.load(v["id"])

    def rename(self):
        vid = self._vid()
        v = [x for x in vehicles.all() if x["id"] == vid][0]
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=v["name"])
        if ok:
            try:
                vehicles.rename(vid, name)
            except ValueError as e:
                forms.error(self, "Vehicles", str(e))
            self.load(vid)

    def forget(self):
        vid = self._vid()
        v = [x for x in vehicles.all() if x["id"] == vid][0]
        if QMessageBox.question(self, "Remove", "Take %s off the list? Its folder stays:\n%s" % (v["name"], v["folder"])) \
                == QMessageBox.Yes:
            vehicles.forget(vid)
            self.load()
