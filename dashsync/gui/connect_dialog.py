"""Connect your phone: a guide that opens by itself while the vehicle has no phone or card, and from the Phone page.

Two ways in: a USB cable (adb, which it offers to download from Google when it is missing, then the steps to switch
on USB debugging, watching for the phone and saying what to do next), or the phone's card in a card reader (found by
its coldshift.dash folder). Listing phones asks the adb server only; no phone is contacted until the user picks it.
"""
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                               QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import adbtool, layout
from . import forms, worker

USB_STEPS = """<ol style="margin-left:-20px">
<li><b>Turn on Developer options.</b> On the phone open Settings, then About phone (on a Samsung: About phone,
Software information), and tap <i>Build number</i> seven times, until it says you're a developer.</li>
<li><b>Turn on USB debugging.</b> In Settings, open Developer options (on a Samsung it's at the bottom of Settings;
on some phones under System) and switch on <i>USB debugging</i>.</li>
<li><b>Plug the phone in</b> to this computer with a USB cable. Some cables only charge: if nothing happens, try
another.</li>
<li><b>Tap Allow</b> when the phone asks to allow USB debugging. Tick <i>Always allow from this computer</i> so it
doesn't ask again.</li>
</ol>"""


def _big(text, sub):
    b = QPushButton("%s\n%s" % (text, sub))
    b.setMinimumHeight(64)
    b.setStyleSheet("text-align: left; padding: 10px 14px")
    return b


class ConnectDialog(QDialog):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.adb = None
        self.devices = []
        self.polling = False
        self.setWindowTitle("Connect your phone")
        self.setMinimumWidth(560)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._choose_page())
        self.pages.addWidget(self._usb_page())
        self.pages.addWidget(self._card_page())

        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(lambda: self._show(0))
        self.later_btn = QPushButton("Not now")
        self.later_btn.clicked.connect(self.reject)
        self.use_btn = QPushButton("Use this phone")
        self.use_btn.setDefault(True)
        self.use_btn.clicked.connect(self._use)
        bottom = QHBoxLayout()
        bottom.addWidget(self.back_btn)
        bottom.addStretch()
        bottom.addWidget(self.later_btn)
        bottom.addWidget(self.use_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(self.pages, 1)
        lay.addLayout(bottom)

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self._poll)
        self._show(0)

    # ---- the pages ----

    def _choose_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        title = QLabel("How is the phone connected to this computer?")
        title.setStyleSheet("font-size: 16px; font-weight: 600")
        lay.addWidget(title)
        lay.addWidget(forms.note("The app copies maps, music and settings onto the phone, and backs up what was "
                                 "recorded on it."))
        usb = _big("With a USB cable (recommended)", "The phone stays in one piece; the app guides you through it.")
        card = _big("With the phone's card in a card reader", "Take the SD card out of the phone first.")
        usb.clicked.connect(lambda: self._show(1))
        card.clicked.connect(lambda: self._show(2))
        lay.addWidget(usb)
        lay.addWidget(card)
        lay.addStretch()
        return w

    def _usb_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.adb_box = QWidget()
        ab = QVBoxLayout(self.adb_box)
        ab.setContentsMargins(0, 0, 0, 8)
        need = QLabel("<b>First, this app needs adb</b>, Google's free tool for talking to Android phones "
                      "(about 16 MB, from Google).")
        need.setWordWrap(True)
        self.download_btn = QPushButton("Download adb…")
        self.download_btn.setDefault(True)
        self.download_btn.clicked.connect(self._download)
        self.download_bar = QProgressBar()
        self.download_bar.hide()
        ab.addWidget(need)
        row = QHBoxLayout()
        row.addWidget(self.download_btn, 0)
        row.addWidget(self.download_bar, 1)
        row.addStretch()
        ab.addLayout(row)
        lay.addWidget(self.adb_box)

        self.steps = QLabel(USB_STEPS)
        self.steps.setWordWrap(True)
        self.steps.setTextFormat(Qt.RichText)
        lay.addWidget(self.steps)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-weight: 600; padding: 6px 0")
        lay.addWidget(self.status)
        self.phones = QListWidget()
        self.phones.setMaximumHeight(90)
        self.phones.itemSelectionChanged.connect(self._buttons)
        self.phones.itemDoubleClicked.connect(lambda _: self._use())
        self.phones.hide()                    # until there is a phone to pick
        lay.addWidget(self.phones)
        self.windows_note = forms.note("On Windows, a phone that is never found may need its maker's USB driver "
                                       "(Samsung's or Huawei's, from their websites).")
        self.windows_note.setVisible(os.name == "nt")
        lay.addWidget(self.windows_note)
        lay.addStretch()
        return w

    def _card_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        intro = QLabel("<b>Put the phone's card in a card reader</b> on this computer. A card the app has used has a "
                       "<i>coldshift.dash</i> folder, and shows up here by itself.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.cards = QListWidget()
        self.cards.setMaximumHeight(110)
        self.cards.itemSelectionChanged.connect(self._buttons)
        self.cards.itemDoubleClicked.connect(lambda _: self._use())
        lay.addWidget(self.cards)
        self.card_status = forms.note("")
        lay.addWidget(self.card_status)
        other = QPushButton("Choose another drive or folder…")
        other.clicked.connect(self._choose_card)
        lay.addWidget(other, 0, Qt.AlignLeft)
        lay.addStretch()
        return w

    def _show(self, i):
        self.pages.setCurrentIndex(i)
        self.back_btn.setVisible(i != 0)
        self.use_btn.setVisible(i != 0)
        self.use_btn.setText("Use this card" if i == 2 else "Use this phone")
        if i == 1:
            self.status.setText("Looking for adb…")
            worker.run(adbtool.status, self._adb_status, self._failed)
        else:
            self.timer.stop()
        if i == 2:
            self._find_cards()
            self.timer.start()
        self._buttons()

    # ---- USB ----

    def _adb_status(self, st):
        self.adb = st["path"] if st["found"] else None
        self.adb_box.setVisible(not self.adb)
        self.steps.setEnabled(bool(self.adb))
        if self.adb:
            self.status.setText("Looking for the phone…")
            self._poll()
            self.timer.start()
        else:
            self.status.setText("")

    def _download(self):
        if QMessageBox.question(
                self, "Download adb",
                "adb is part of Google's Android SDK Platform-Tools, under the Android SDK licence:\n%s\n\n"
                "Do you accept the licence and want the app to download it?" % adbtool.LICENCE_URL) != QMessageBox.Yes:
            return
        self.download_btn.setEnabled(False)
        self.download_bar.setValue(0)
        self.download_bar.show()

        def progress(done, total):
            self.download_bar.setMaximum(max(1, int(total or 0)))
            self.download_bar.setValue(int(done))

        def finished(_):
            self.download_bar.hide()
            worker.run(adbtool.status, self._adb_status, self._failed)

        def failed(msg):
            self.download_btn.setEnabled(True)
            self.download_bar.hide()
            self._failed(msg)
        worker.run(lambda report: adbtool.setup(accept_licence=True, progress=report), finished, failed, progress)

    def _poll(self):
        if self.pages.currentIndex() == 2:
            self._find_cards()
            return
        if not self.adb or self.polling:
            return
        self.polling = True

        def got(devs):
            self.polling = False
            self._devices(devs)

        def failed(msg):
            self.polling = False
            self.status.setText("adb did not answer: " + msg)
        worker.run(lambda: adbtool.list_devices(self.adb), got, failed)

    def _devices(self, devs):
        usb = [d for d in devs if not d["wifi"]]
        ready = [d for d in usb if d["state"] == "device"]
        waiting = [d for d in usb if d["state"] == "unauthorized"]
        if ready:
            self.status.setText("Found it." if len(ready) == 1 else "Found %d phones: pick the one in this car."
                                % len(ready))
        elif waiting:
            self.status.setText("The phone is plugged in. Now tap Allow on the phone (tick Always allow from this "
                                "computer).")
        elif any(d["state"] == "offline" for d in usb):
            self.status.setText("The phone isn't answering. Unplug the cable and plug it in again.")
        else:
            self.status.setText("No phone yet. Follow the steps above and plug it in; it shows up here by itself.")
        chosen = self._chosen_serial()
        if [d["serial"] for d in ready] == [self.phones.item(i).data(Qt.UserRole) for i in range(self.phones.count())]:
            return
        self.devices = ready
        self.phones.clear()
        for d in ready:
            it = QListWidgetItem("%s  (USB)" % ((d["model"] or "Android phone").replace("_", " ")))
            it.setData(Qt.UserRole, d["serial"])
            self.phones.addItem(it)
            if d["serial"] == chosen or len(ready) == 1:
                it.setSelected(True)
        self.phones.setVisible(bool(ready))
        self._buttons()

    def _chosen_serial(self):
        items = self.phones.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    # ---- card reader ----

    def _find_cards(self):
        def got(found):
            have = [self.cards.item(i).data(Qt.UserRole) for i in range(self.cards.count())]
            if found == have:
                return
            self.cards.clear()
            for path in found:
                it = QListWidgetItem("%s   (%s)" % (os.path.basename(path.rstrip("/\\")) or path, path))
                it.setData(Qt.UserRole, path)
                self.cards.addItem(it)
            if len(found) == 1:
                self.cards.item(0).setSelected(True)
            self.card_status.setText("" if found else "No card with a coldshift.dash folder yet. A new card works too: "
                                     "choose it below.")
            self._buttons()
        worker.run(layout.mounted_cards, got, self._failed)

    def _choose_card(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose the card (its top folder)")
        if not folder:
            return
        it = QListWidgetItem("%s   (%s)" % (os.path.basename(folder.rstrip("/\\")) or folder, folder))
        it.setData(Qt.UserRole, folder)
        self.cards.addItem(it)
        self.cards.clearSelection()
        it.setSelected(True)

    # ---- choosing ----

    def _buttons(self):
        i = self.pages.currentIndex()
        if i == 1:
            self.use_btn.setEnabled(bool(self.phones.selectedItems()) and not self.state.busy)
        elif i == 2:
            self.use_btn.setEnabled(bool(self.cards.selectedItems()) and not self.state.busy)

    def _use(self):
        if not self.use_btn.isEnabled():
            return
        if self.pages.currentIndex() == 1:
            serial = self._chosen_serial()
            if not serial:
                return
            self.timer.stop()
            self.status.setText("Checking the phone…")

            def checked(st):
                if not st["installed"] and QMessageBox.question(
                        self, "Use this phone",
                        "This phone doesn't have the Coldshift Dash app yet. Use it for this vehicle anyway? The app "
                        "can be installed later; syncing puts a coldshift.dash folder on its card.") != QMessageBox.Yes:
                    self.timer.start()
                    return
                self.state.use_phone(serial)
                self.accept()
            worker.run(lambda: adbtool.app_status(self.adb, serial), checked, self._failed)
        else:
            items = self.cards.selectedItems()
            if items:
                self.state.use_card(items[0].data(Qt.UserRole))
                self.accept()

    def _failed(self, msg):
        forms.error(self, "Connect your phone", msg)

    def done(self, r):
        self.timer.stop()
        super().done(r)
