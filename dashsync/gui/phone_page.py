"""Phone page: which phone (or card in a card reader) the open vehicle works on, and Wi-Fi.

Listing comes from the adb server and contacts no phone; only a phone the user picks is ever queried
(this matters on a computer that also has a work phone attached).
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from .. import adbtool, layout
from . import forms, worker

STATUS = {"device": "Ready", "unauthorized": "Waiting: tap “Allow USB debugging” on the phone",
          "offline": "Offline: unplug and replug the cable, or toggle USB debugging"}


class PhonePage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.adb = None
        self.devices = []

        # adb: one line while it works, details on request
        box = QGroupBox("Phone connection")
        self.adb_label = QLabel("Looking for adb…")
        self.adb_label.setWordWrap(True)
        self.adb_detail = forms.note("")
        self.adb_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.download_btn = QPushButton("Download adb…")
        self.choose_btn = QPushButton("Choose adb…")
        self.advanced_btn = QPushButton("Advanced")
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.toggled.connect(self._advanced)
        self.download_btn.clicked.connect(self.download_adb)
        self.choose_btn.clicked.connect(self.choose_adb)
        row = QHBoxLayout()
        row.addWidget(self.adb_label, 1)
        for b in (self.download_btn, self.choose_btn, self.advanced_btn):
            row.addWidget(b)
        lay = QVBoxLayout(box)
        lay.addLayout(row)
        lay.addWidget(self.adb_detail)

        phones = QGroupBox("Phones")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Phone", "Connection", "Status", ""])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._selection)
        self.table.doubleClicked.connect(self.use_selected)
        self.empty = forms.note("No phones found. “Connect a phone…” shows how: USB debugging and a cable, or the "
                                "phone's card in a card reader.")
        self.connect_btn = QPushButton("Connect a phone…")
        self.connect_btn.setToolTip("A guide: USB debugging and the cable, or a card reader")
        self.connect_btn.clicked.connect(self.connect_phone)
        self.refresh_btn = QPushButton("Refresh")
        self.use_btn = QPushButton("Use this phone")
        self.card_btn = QPushButton("Use a card reader instead…")
        self.refresh_btn.clicked.connect(self.refresh)
        self.use_btn.clicked.connect(self.use_selected)
        self.card_btn.clicked.connect(self.use_card)
        row = QHBoxLayout()
        for b in (self.connect_btn, self.refresh_btn, self.use_btn, self.card_btn):
            row.addWidget(b)
        row.addStretch()
        lay = QVBoxLayout(phones)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.empty)
        lay.addLayout(row)

        chosen = QGroupBox("In use")
        self.chosen_label = QLabel()
        self.chosen_label.setStyleSheet("font-weight: 600")
        self.app_label = QLabel()
        self.app_label.setWordWrap(True)
        self.wifi_btn = QPushButton("Switch to Wi-Fi")
        self.wifi_btn.setToolTip("Lets you unplug the cable. The phone forgets this when it restarts.")
        self.wifi_btn.clicked.connect(self.wifi_on)
        lay = QVBoxLayout(chosen)
        lay.addWidget(self.chosen_label)
        lay.addWidget(self.app_label)
        row = QHBoxLayout()
        row.addWidget(self.wifi_btn)
        row.addStretch()
        lay.addLayout(row)

        page = QVBoxLayout(self)
        page.addWidget(box)
        page.addWidget(phones, 1)
        page.addWidget(chosen)

        state.target_changed.connect(self.show_chosen)
        state.busy_changed.connect(self._selection)
        self.find_adb()

    # ---- adb ----

    def find_adb(self):
        worker.run(adbtool.status, self._adb_status, self._error)

    def _advanced(self, on):
        self.adb_detail.setVisible(on or not self.adb)
        self.choose_btn.setVisible(on or not self.adb)

    def _adb_status(self, st):
        self.adb = st["path"] if st["found"] else None
        if st["found"]:
            self.adb_label.setText("Ready to talk to phones over USB and Wi-Fi.")
            self.adb_detail.setText("adb %s (%s): %s" % (st["version"], st["source"], st["path"]))
        else:
            self.adb_label.setText("adb (Google's tool for talking to Android phones) is not installed.")
            self.adb_detail.setText(st["hint"])
        self.download_btn.setVisible(not st["found"])
        self.advanced_btn.setVisible(bool(st["found"]))
        self._advanced(self.advanced_btn.isChecked())
        self.refresh()

    def download_adb(self):
        ans = QMessageBox.question(
            self, "Download adb",
            "adb is part of Google's Android SDK Platform-Tools, under the Android SDK licence:\n%s\n\n"
            "Do you accept the licence and want the tool to download it (about 16 MB)?" % adbtool.LICENCE_URL)
        if ans != QMessageBox.Yes:
            return
        self.adb_label.setText("Downloading adb…")
        worker.run(lambda: adbtool.setup(accept_licence=True), lambda _: self.find_adb(), self._error)

    def choose_adb(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose adb")
        if not path:
            return
        try:
            adbtool.set_path(path)
        except ValueError as e:
            self._error(str(e))
            return
        self.find_adb()

    # ---- phones ----

    def connect_phone(self):
        from .connect_dialog import ConnectDialog
        if ConnectDialog(self.state, self).exec():
            self.find_adb()           # adb may have just been downloaded

    def refresh(self):
        if not self.adb:
            self.state.online = set()
            self.state.names_changed.emit()
            self.table.setRowCount(0)
            self.empty.show()
            self.show_chosen()
            return
        worker.run(lambda: adbtool.list_devices(self.adb), self._devices, self._error)

    def _devices(self, devs):
        self.devices = devs
        self.state.online = {d["serial"] for d in devs if d["state"] == "device"}
        for d in devs:
            if d["model"]:
                self.state.models[d["serial"]] = d["model"]
        self.state.names_changed.emit()
        bold = QFont()
        bold.setBold(True)
        self.table.setRowCount(len(devs))
        for r, d in enumerate(devs):
            cells = [(d["model"] or "Unknown phone").replace("_", "-"), "Wi-Fi" if d["wifi"] else "USB",
                     STATUS.get(d["state"], d["state"]), "✓ in use" if d["serial"] == self.state.serial else ""]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setToolTip("Serial " + d["serial"])
                if d["serial"] == self.state.serial:
                    it.setFont(bold)
                self.table.setItem(r, c, it)
        self.empty.setVisible(not devs)
        self._selection()
        self.show_chosen()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.devices[rows[0].row()] if rows else None

    def _selection(self):
        d = self._selected()
        self.use_btn.setEnabled(bool(d) and d["state"] == "device" and d["serial"] != self.state.serial
                                and not self.state.busy)
        self.use_btn.setDefault(not self.state.has_target())

    def use_selected(self):
        d = self._selected()
        if not d or d["state"] != "device" or self.state.busy:
            return
        name = (d["model"] or "this phone").replace("_", "-")

        def checked(st):
            if not st["installed"] and QMessageBox.question(
                    self, "Use this phone",
                    "%s does not have the coldshift.dash app. Use it for this vehicle anyway? Syncing writes a "
                    "coldshift.dash folder onto its card." % name) != QMessageBox.Yes:
                return
            self.state.use_phone(d["serial"])
            self.refresh()
        worker.run(lambda: adbtool.app_status(self.adb, d["serial"]), checked, self._error)

    def use_card(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose the card (its top folder)")
        if not folder:
            return
        if not os.path.ismount(folder) and not os.path.isdir(os.path.join(folder, layout.APP_DIR)) and \
                QMessageBox.question(self, "Card reader",
                                     "%s is not the top of a drive and has no %s folder yet, so it may not be the "
                                     "phone's card. Syncing writes a %s folder into it. Use it anyway?"
                                     % (folder, layout.APP_DIR, layout.APP_DIR)) != QMessageBox.Yes:
            return
        self.state.use_card(folder)

    def show_chosen(self):
        self._selection()
        self.chosen_label.setText(self.state.label()[0].upper() + self.state.label()[1:])
        serial = self.state.serial
        attached = any(d["serial"] == serial and d["state"] == "device" for d in self.devices)
        self.wifi_btn.setEnabled(bool(serial) and attached and ":" not in (serial or ""))
        self.app_label.setText("")
        if serial and attached and self.adb:
            self.app_label.setText("Checking the app…")
            worker.run(lambda: adbtool.app_status(self.adb, serial), self._app, self._error)
        elif serial and ":" in serial:
            self.app_label.setText("Not connected. Over Wi-Fi the phone forgets the connection when it restarts: "
                                   "plug it in with USB and press Switch to Wi-Fi again, or use its USB row.")
        elif serial:
            self.app_label.setText("Not connected right now: plug it in, then press Refresh.")
        elif self.state.card:
            self.app_label.setText(self.state.card)
        else:
            self.app_label.setText("Pick the vehicle's phone in the list and press Use this phone.")

    def _app(self, st):
        phone = "%s, Android %s. " % (st["model"], st["android"])
        if st["installed"]:
            self.app_label.setText(phone + "coldshift.dash %s (build %s) is installed." % (st["version"], st["version_code"]))
        else:
            self.app_label.setText(phone + "coldshift.dash is not installed.")

    def wifi_on(self):
        usb = self.state.serial
        self.wifi_btn.setEnabled(False)
        self.app_label.setText("Switching to Wi-Fi…")

        def done(new_serial):
            self.state.use_phone(new_serial)
            self.refresh()
        worker.run(lambda: adbtool.wifi_enable(self.adb, usb), done, self._error)

    def _error(self, msg):
        forms.error(self, "", msg)
        self._selection()
