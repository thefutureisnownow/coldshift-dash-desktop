"""Music page: index the vehicle's music and put it on the card (mirror.push_music)."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .. import layout, mirror, paths
from . import forms, worker
from .state import Progress


def _mb(n):
    return "%.1f GB" % (n / 1e9) if n >= 1e9 else "%.0f MB" % (n / 1e6)


class MusicPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.checked_once = False
        self.result = ""       # what the last push did, shown above the check that follows it

        ws = QGroupBox("This vehicle's music")
        self.ws_label = QLabel()
        self.ws_label.setWordWrap(True)
        self.ws_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary = QLabel()
        self.summary.setStyleSheet("font-weight: 600")
        add = QPushButton("Add music\u2026")
        add.setToolTip("Copy a folder of music into this vehicle (artist and album folders are kept)")
        add.clicked.connect(self.add_music)
        change = QPushButton(forms.SHOW_FOLDER)
        change.clicked.connect(self.open_folder)
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(self.summary)
        col.addWidget(self.ws_label)
        row.addLayout(col, 1)
        row.addWidget(add)
        row.addWidget(change)
        QVBoxLayout(ws).addLayout(row)
        forms.muted(self.ws_label)

        plan = QGroupBox("Compared with the card")
        self.to_copy = QLabel()
        self.same = QLabel()
        self.conflicts = QLabel()
        self.extra = QLabel()
        self.library = QLabel()
        self.names = QLabel()
        for w in (self.to_copy, self.same, self.conflicts, self.extra, self.library, self.names):
            w.setWordWrap(True)
        form = forms.form(plan)
        form.addRow("To copy", self.to_copy)
        form.addRow("Already on the card", self.same)
        form.addRow("Different on the card", self.conflicts)
        form.addRow("Only on the card", self.extra)
        form.addRow("Index and covers", self.library)
        form.addRow("Song names", self.names)


        self.overwrite = QCheckBox("Replace songs on the card that differ from this computer's")
        self.delete_extra = QCheckBox("Remove songs from the card that are not on this computer")
        self.check_btn = QPushButton("Check card")
        self.check_btn.clicked.connect(self.check)
        self.push_btn = QPushButton("Sync to card")
        self.push_btn.setDefault(True)
        self.push_btn.clicked.connect(self.push)
        self.overwrite.toggled.connect(lambda *_: self.check())
        buttons = QHBoxLayout()
        buttons.addWidget(self.push_btn)
        buttons.addWidget(self.check_btn)
        buttons.addStretch()
        self.bar = Progress(state)
        self.bar.hide()
        self.note = QLabel()
        self.note.setWordWrap(True)

        self.plan = plan
        page = QVBoxLayout(self)
        page.addWidget(ws)
        page.addWidget(plan)
        page.addWidget(self.overwrite)
        page.addWidget(self.delete_extra)
        page.addStretch()
        page.addWidget(self.note)
        page.addLayout(buttons)

        state.target_changed.connect(self._target_changed)
        state.busy_changed.connect(self._buttons)
        state.busy_changed.connect(self._phone_free)
        self.show_workspace()

    def workspace(self):
        return paths.load_config().get("workspace")

    def music_dir(self):
        ws = self.workspace()
        return os.path.join(ws, *layout.MUSIC_DIR.split("/")) if ws else None

    def songs(self):
        """(songs, bytes) in the vehicle's music folder."""
        n = size = 0
        d = self.music_dir()
        for root, _, files in os.walk(d) if d and os.path.isdir(d) else ():
            for f in files:
                if f.lower().endswith(layout.AUDIO_EXT) and not f.startswith("."):
                    n += 1
                    size += os.path.getsize(os.path.join(root, f))
        return n, size

    def show_workspace(self):
        d = self.music_dir()
        if not d:
            self.summary.setText("No vehicle open.")
            self.ws_label.setText("")
        else:
            n, size = self.songs()
            self.summary.setText("%d songs, %s" % (n, _mb(size)) if n else
                                 "No music yet: press Add music\u2026, or put songs in this folder")
            self.ws_label.setText(d)
        self._buttons()

    def open_folder(self):
        if self.music_dir():
            forms.show_folder(self.music_dir())

    def add_music(self):
        src = QFileDialog.getExistingDirectory(self, "A folder of music to add to this vehicle")
        if not src or not self.music_dir():
            return
        dest = os.path.join(self.music_dir(), os.path.basename(src.rstrip(os.sep)))
        if os.path.exists(dest):
            forms.error(self, "Add music", "this vehicle already has a folder called %s" % os.path.basename(dest))
            return
        self.note.setText("Adding %s\u2026" % os.path.basename(dest))

        def copy():
            import shutil
            shutil.copytree(src, dest)

        def done(_):
            self.show_workspace()
            self.note.setText("Added %s." % os.path.basename(dest))
            self.checked_once = False
            if self.isVisible():
                self.showEvent(None)
        worker.run(copy, done, lambda m: forms.error(self, "Add music", m))

    def _target_changed(self):
        self._clear()
        self.checked_once = False         # checked again the next time the page is shown
        self._buttons()
        if self.isVisible():
            self.showEvent(None)

    def _ready(self):
        return bool(self.workspace()) and self.state.has_target() and not self.state.busy and self.songs()[0] > 0

    def _buttons(self):
        self.check_btn.setEnabled(self._ready())
        self.push_btn.setEnabled(self._ready())
        if not self.state.has_target():
            self.note.setText("Choose a phone or card on the Phone page first.")
        elif self.state.busy and not self.bar.isVisible():
            self.note.setText("Waiting for %s to finish." % self.state.busy)

    def _phone_free(self):
        """Shown while another job had the phone: look now that it is free."""
        if not self.state.busy and self.isVisible() and not self.checked_once:
            self.showEvent(None)

    def showEvent(self, e):
        if e is not None:
            super().showEvent(e)
        self.show_workspace()
        if not self.checked_once and self._ready():
            self.checked_once = True
            self.check()

    def _clear(self):
        for w in (self.to_copy, self.same, self.conflicts, self.extra, self.library, self.names):
            w.setText("")

    # ---- check and push ----

    def _start(self, text, what):
        if not self.state.begin(what):
            return False
        self._buttons()
        self.bar.setRange(0, 0)
        self.bar.show()
        self.note.setText(text)
        self.state.watch(self.note)
        return True

    def _stop(self):
        self.state.end()
        self.bar.hide()
        self._buttons()

    def _progress(self, info, _):
        if info[0] == "index":
            _, done, total, rel = info
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            self.note.setText("Indexing %d of %d songs…" % (done, total))
        else:
            _, i, n, done, total, name = info
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total) if total else 1000)
            self.note.setText("Copying %d of %d (%s of %s): %s" % (i, n, _mb(done), _mb(total), name))

    def _run(self, dry_run, overwrite=False, delete_extra=False):
        target = self.state.target()
        ws = self.workspace()

        def work(report):
            return mirror.push_music(target, ws, overwrite=overwrite, delete_extra=delete_extra, dry_run=dry_run,
                                     progress=lambda i, n, d, t, name: report(("copy", i, n, d, t, name), None),
                                     indexing=lambda d, t, rel: report(("index", d, t, rel), None))
        return work

    def check(self):
        if not self._ready():
            return
        try:
            work = self._run(dry_run=True, overwrite=self.overwrite.isChecked())
        except SystemExit as e:
            self._error(str(e.code))
            return
        if self._start("Comparing this vehicle's music with %s\u2026" % self.state.label(), "checking the music"):
            worker.run(work, self._checked, self._failed, progress=self._progress)

    def _checked(self, r):
        self._stop()
        self._show_plan(r)
        n = len(r["music"]["copy"])
        status = "Nothing to copy." if not n and not r["stale_covers"] else "Ready: press “Sync to card”."
        self.note.setText(self.result + "\n" + status if self.result else status)
        self.result = ""

    def _show_plan(self, r):
        m = r["music"]
        self.to_copy.setText("%d songs (%s)" % (len(m["copy"]), _mb(sum(c[2] for c in m["copy"]))) if m["copy"] else "nothing")
        self.same.setText("%d files (songs, and pictures in their folders)" % m["same"])
        self.conflicts.setText(("%d — kept unless you tick “Replace”: %s" % (len(m["conflicts"]), ", ".join(
            c[0] for c in m["conflicts"][:3]))) if m["conflicts"] else "none")
        self.extra.setText(("%d — kept unless you tick “Remove”: %s" % (len(m["extra"]), ", ".join(
            e[0] for e in m["extra"][:3]))) if m["extra"] else "none")
        covers = r["library_copy"] - 1          # the index itself is always refreshed
        self.library.setText("%d songs indexed; the index%s is refreshed%s" % (
            r["index"]["tracks"], " and %d new cover%s" % (covers, "" if covers == 1 else "s") if covers else "",
            "; %d unused covers are removed" % r["stale_covers"] if r["stale_covers"] else ""))
        names = ""
        if m["renamed"]:
            names = "%d have emoji, which this phone garbles; on the card each emoji is its code, like U+1F3B6" % m["renamed"]
            if m["move"]:
                names += "; %d already there get renamed" % len(m["move"])
        self.names.setText(names or "all fine as they are")
        self.last_extra = len(m["extra"])

    def push(self):
        if not self._ready():
            return
        delete = self.delete_extra.isChecked()
        if delete:
            n = getattr(self, "last_extra", None)
            what = "%d songs" % n if n is not None else "every song"
            ans = QMessageBox.question(self, "Remove songs from the card",
                                       "This deletes %s on the card that this computer does not have. "
                                       "They are not copied anywhere first. Go ahead?" % what)
            if ans != QMessageBox.Yes:
                return
        try:
            work = self._run(dry_run=False, overwrite=self.overwrite.isChecked(), delete_extra=delete)
        except SystemExit as e:
            self._error(str(e.code))
            return
        if self._start("Indexing\u2026", "syncing music"):
            worker.run(work, self._pushed, self._failed, progress=self._progress)

    def _pushed(self, r):
        self._stop()
        parts = ["Copied %d songs (%s)" % (r["copied"], _mb(r["bytes"]))]
        if r["moved"]:
            parts.append("renamed %d for this phone" % r["moved"])
        if r["deleted"]:
            parts.append("removed %d from the card" % r["deleted"])
        if r["app"]:
            parts.append("the app " + r["app"])
        elif self.state.serial:
            parts.append("the app is not running; it reads the new music when it starts")
        else:
            parts.append("the app reloads when the card goes back in")
        self.result = "; ".join(parts) + "."
        self.delete_extra.setChecked(False)
        self.check()      # show the card as it is now

    def _failed(self, msg):
        self._stop()
        self.note.setText("")
        self._error(msg)

    def _error(self, msg):
        forms.error(self, "Music", msg)
