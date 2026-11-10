"""A Sync to card button that says whether the card is up to date ("3 changes not on the card yet"),
for pages whose edits are saved at once but reach the phone only when synced (Voices, Vehicle)."""
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .. import paths, profile
from . import forms, worker


class SyncBar(QWidget):
    """`count(target)` says how many changes the card lacks (run off the UI thread); `run(target)` syncs
    and returns what `done(result)` turns into a sentence. Holds the shared busy flag while it works."""
    def __init__(self, state, what, count, run, done):
        super().__init__()
        self.state, self.what, self.count, self.run, self.done = state, what, count, run, done
        self.btn = QPushButton("Sync to card")
        self.btn.setDefault(True)
        self.btn.clicked.connect(self.sync)
        self.label = QLabel()
        self.label.setWordWrap(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.btn)
        lay.addWidget(self.label, 1)
        state.busy_changed.connect(self.buttons)
        state.target_changed.connect(self.recheck)
        self.missed = False         # a recheck was asked for while another job had the phone
        self.buttons()

    def buttons(self):
        if self.missed and not self.state.busy:
            self.missed = False
            self.recheck()
        ok = self.state.has_target() and not self.state.busy
        self.btn.setEnabled(ok)
        self.btn.setToolTip("Wait for %s to finish" % self.state.busy if self.state.busy else
                            "" if self.state.has_target() else "Choose a phone or card on the Phone page first")

    def recheck(self):
        """Compares with the card (quietly does nothing while another job has the phone)."""
        if not self.state.has_target():
            self.label.setText("No phone or card chosen.")
            return
        if self.state.busy:
            self.missed = True
            return
        try:
            target = self.state.target()
        except SystemExit:
            return

        def shown(n):
            self.label.setText("On the card: up to date." if not n else
                               "%d change%s not on the card yet." % (n, "" if n == 1 else "s"))
        worker.run(lambda: self.count(target), shown, lambda msg: self.label.setText(""))

    def sync(self):
        try:
            target = self.state.target()
        except SystemExit as e:
            forms.error(self, "Sync to card", str(e.code))
            return
        if not self.state.begin(self.what):
            return
        self.label.setText("Copying to %s…" % self.state.label())
        self.state.watch(self.label)

        def ok(r):
            self.state.end()
            self.label.setText(self.done(r))

        def failed(msg):
            self.state.end()
            self.label.setText("")
            forms.error(self, "Sync to card", msg)
        worker.run(lambda: self.run(target), ok, failed)


def look_syncbar(state):
    """The bar for the vehicle's look (its pictures, title, colours and pages: one profile on the card)."""
    vehicle = lambda: paths.load_config().get("workspace")
    return SyncBar(state, "syncing the look",
                   lambda t: profile.sync(t, vehicle(), dry_run=True)["files"],
                   lambda t: profile.sync(t, vehicle()),
                   lambda r: ("On the card: up to date. The app " + r["app"] + "." if r["app"] else
                              "On the card: up to date." if not r["changed"] else
                              "Copied; the app shows it when it next starts."))
