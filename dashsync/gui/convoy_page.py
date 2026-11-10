"""Convoy page: the convoy server's address, and convoys: start one (with a password) or join one from its
link, show its QR code (the car's phone scans it), copy the link to send the other drivers (or someone
following from a browser), open the watch page, and put it on the phone (dashsync/convoy.py)."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from .. import convoy, paths
from . import forms, worker


class ConvoyPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        # {"server", "token", "name", "password", "key"?}: kept on this computer, for putting it on the phone (and the
        # key, from starting it here, for ending it)
        self.current = paths.global_config().get("convoy_last")

        srv = QGroupBox("Convoy host")
        sf = forms.form(srv)
        self.server = QLineEdit(convoy.server())
        self.server.setPlaceholderText("http://192.168.0.10:8080 (a laptop on the Wi-Fi) or https://convoy.example.com")
        self.server.editingFinished.connect(self.save_server)
        row = QHBoxLayout()
        row.addWidget(self.server, 1)
        self.check_btn = QPushButton("Check")
        self.check_btn.clicked.connect(self.check)
        row.addWidget(self.check_btn)
        sf.addRow("Address", row)
        self.key = QLineEdit(convoy.start_key(convoy.server()) if convoy.server() else "")
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("only if the host has one")
        self.key.editingFinished.connect(self.save_key)
        sf.addRow("Start key", self.key)
        self.server_note = forms.note("The relay every car in a convoy uses (run your own: "
                                      "github.com/thefutureisnownow/coldshift-dash-convoy). A start key is only needed to "
                                      "start a convoy, never to join one.")
        sf.addRow("", self.server_note)
        self.server_push = QPushButton("Host to card")
        self.server_push.setToolTip("Put the host's address and start key on the phone (it can also be set on the "
                                    "phone's Convoy page; the latest change wins)")
        self.server_push.clicked.connect(lambda: self.to_card(None))
        pr0 = QHBoxLayout()
        pr0.addWidget(self.server_push)
        pr0.addStretch()
        sf.addRow("", pr0)

        box = QGroupBox("Convoy")
        v = QVBoxLayout(box)
        v.addWidget(forms.note("Start a convoy, then have the other drivers scan its QR code (Convoy, Scan to join) "
                               "or send them the link. Opened in a browser, the link follows the convoy."))
        top = QHBoxLayout()
        self.start_btn = QPushButton("Start a convoy…")
        self.start_btn.clicked.connect(self.start)
        self.join_btn = QPushButton("Join from a link…")
        self.join_btn.clicked.connect(self.join)
        top.addWidget(self.start_btn)
        top.addWidget(self.join_btn)
        top.addStretch()
        v.addLayout(top)
        f = forms.form()
        self.name = QLabel()
        self.name.setStyleSheet("font-size: 18px; font-weight: 600")
        self.qr = QLabel()
        self.qr.setFixedSize(180, 180)
        self.qr.setAlignment(Qt.AlignCenter)
        self.locked = forms.note("")
        self.link = QLineEdit()
        self.link.setReadOnly(True)
        lr = QHBoxLayout()
        lr.addWidget(self.link, 1)
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(self.copy)
        self.open_btn = QPushButton("Open the watch page")
        self.open_btn.clicked.connect(self.open_page)
        lr.addWidget(self.copy_btn)
        lr.addWidget(self.open_btn)
        f.addRow("Convoy", self.name)
        f.addRow("", self.locked)
        f.addRow("Link", lr)
        details = QHBoxLayout()
        details.addLayout(f, 1)
        details.addWidget(self.qr, 0, Qt.AlignTop)          # the QR code beside the details, for scanning off the screen
        v.addLayout(details)
        self.push_btn = QPushButton("Convoy to card")
        self.push_btn.setDefault(True)
        self.push_btn.setToolTip("Put this convoy on the phone: it joins by itself")
        self.push_btn.clicked.connect(lambda: self.to_card(self.current))
        self.end_btn = QPushButton("End the convoy…")
        self.end_btn.setToolTip("Ends it for everyone in it (you started it here)")
        self.end_btn.clicked.connect(self.end)
        pr = QHBoxLayout()
        pr.addWidget(self.push_btn)
        pr.addStretch()
        pr.addWidget(self.end_btn)
        v.addLayout(pr)

        self.note = QLabel()
        self.note.setWordWrap(True)
        page = QVBoxLayout(self)
        page.addWidget(srv)
        page.addWidget(box)
        page.addWidget(self.note)
        page.addStretch()
        state.busy_changed.connect(self._buttons)
        state.target_changed.connect(self._buttons)
        self._show()

    # ---- showing ----

    def _show(self):
        c = self.current
        self.name.setText(c["name"] if c else "None yet")
        self.link.setText(convoy.link(c["server"], c["token"]) if c else "")
        self.locked.setText(("Password protected: joining needs the password too." if c.get("password")
                             else "No password: anyone with the link or QR code can join.") if c else "")
        self.qr.setPixmap(QPixmap())
        if c:
            worker.run(lambda: convoy.qr_png(c["server"], c["token"]), self._qr, lambda msg: self.qr.setText("No QR code"))
        self._buttons()

    def _qr(self, png):
        pm = QPixmap()
        pm.loadFromData(png)
        self.qr.setPixmap(pm.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _buttons(self):
        has_server = bool(self.server.text().strip())
        ok = bool(paths.load_config().get("workspace")) and self.state.has_target() and not self.state.busy
        self.check_btn.setEnabled(has_server)
        self.start_btn.setEnabled(has_server)
        self.join_btn.setEnabled(True)
        self.server_push.setEnabled(ok and has_server)
        for b in (self.copy_btn, self.open_btn):
            b.setEnabled(bool(self.current))
        self.push_btn.setEnabled(ok and bool(self.current))
        self.end_btn.setEnabled(bool(self.current and self.current.get("key")))

    def _remember(self, c):
        self.current = c
        g = paths.global_config()
        g["convoy_last"] = c
        paths.save_global(g)
        self._show()

    # ---- the server ----

    def save_server(self):
        try:
            url = convoy.set_server(self.server.text())
        except ValueError as e:
            forms.error(self, "Convoy server", str(e))
            return None
        self.server.setText(url)
        if url:
            self.key.setText(convoy.start_key(url))          # each host's own
        self._buttons()
        return url

    def save_key(self):
        url = self.server.text().strip().rstrip("/")
        if url:
            convoy.set_start_key(url, self.key.text())

    def _net(self, what, fn, done):
        self.note.setText(what + "…")
        self.setEnabled(False)

        def ok(r):
            self.setEnabled(True)
            done(r)

        def failed(msg):
            self.setEnabled(True)
            self.note.setText("")
            forms.error(self, "Convoy", msg)
        worker.run(fn, ok, failed)

    def check(self):
        url = self.save_server()
        if url:
            self._net("Asking %s" % url, lambda: convoy.check(url),
                      lambda r: self.note.setText("The convoy server at %s answers." % url))

    # ---- convoys ----

    def start(self):
        url = self.save_server()
        if not url:
            return
        name, ok = QInputDialog.getText(self, "Start a convoy", "Name it (the drivers see this):", text="Sunday run")
        if not ok:
            return
        password, ok = QInputDialog.getText(self, "Start a convoy", "A password (recommended; empty for none):",
                                            QLineEdit.Password)
        if not ok:
            return

        def done(c):
            if c is None:
                return
            self._remember({"server": url, "token": c["token"], "name": c["name"], "password": password, "key": c["key"]})
            self.note.setText("Started. Let the other drivers scan the QR code or send them the link (and the "
                              "password), and Convoy to card to put it on this phone.")

        def go():
            try:
                return convoy.start(url, name, password)
            except convoy.StartKeyNeeded as e:
                return e                                      # asked for on this side, then tried again

        def started(r):
            if not isinstance(r, convoy.StartKeyNeeded):
                return done(r)
            self.note.setText("")
            key, ok = QInputDialog.getText(self, "Start key", "%s.\nThe host's start key:" % str(r).capitalize(),
                                           QLineEdit.Password)
            if not ok or not key.strip():
                return
            convoy.set_start_key(url, key)
            self.key.setText(key.strip())
            self._net("Starting a convoy", go, started)
        self._net("Starting a convoy", go, started)

    def join(self):
        text, ok = QInputDialog.getText(self, "Join a convoy", "Paste the convoy's link:")
        if not ok or not text.strip():
            return
        try:
            base, token = convoy.read_link(text)
        except ValueError as e:
            forms.error(self, "Join a convoy", str(e))
            return
        password, ok = QInputDialog.getText(self, "Join a convoy", "Its password (empty if it has none):",
                                            QLineEdit.Password)
        if not ok:
            return
        if base != self.server.text().strip().rstrip("/"):
            self.server.setText(base)
            convoy.set_server(base)
        self._remember({"server": base, "token": token, "name": "Convoy", "password": password})
        self.note.setText("Ready to join. Convoy to card puts it on the phone, which joins by itself.")

    def end(self):
        c = self.current
        if not c or QMessageBox.question(self, "End the convoy", "End %s for everyone in it?" % c["name"]) != QMessageBox.Yes:
            return

        def done(r):
            self._remember(None)
            self.note.setText("The convoy has ended: everyone in it was told.")
        self._net("Ending the convoy", lambda: convoy.end(c["server"], c["token"], c["key"]), done)

    def copy(self):
        QGuiApplication.clipboard().setText(self.link.text())
        self.note.setText("The link is copied.")

    def open_page(self):
        QDesktopServices.openUrl(QUrl(self.link.text()))

    # ---- the phone ----

    def to_card(self, join):
        url = self.save_server() if join is None else join["server"]
        if not url:
            return
        try:
            target = self.state.target()
        except SystemExit as e:
            forms.error(self, "Convoy", str(e.code))
            return
        if not self.state.begin("putting the convoy on the card"):
            return
        v = paths.load_config().get("workspace")

        def ok(reply):
            self.state.end()
            self.note.setText(("The phone has the convoy%s." if join else "The phone has the server's address%s.")
                              % ("; the app " + reply if reply else " (the app reads it when it next starts)"))

        def failed(msg):
            self.state.end()
            forms.error(self, "Convoy", msg)
        worker.run(lambda: convoy.to_card(target, v, url, join), ok, failed)
