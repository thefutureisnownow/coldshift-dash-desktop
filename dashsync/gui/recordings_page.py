"""Recordings page: what the dashcam left on the card, pull it, then free up the card on request."""
import os

from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from .. import paths, recordings
from . import forms, worker
from .state import Progress
from .mix_dialog import MixDialog

KINDS = {"clip": "Clip", "mark": "Mark", "trip": "Trip log", "interior": "Interior shot", "sound": "Sound"}


def _mb(n):
    return ("%.1f GB" % (n / 1e9) if n >= 1e9 else "%.0f MB" % (n / 1e6) if n >= 1e6
            else "%.0f KB" % (n / 1e3) if n >= 1e3 else "under 1 KB")


def recordings_dest():
    """Where the Recordings tab keeps its copies (the vehicle's recordings/ folder unless one was chosen)."""
    cfg = paths.load_config()
    if cfg.get("recordings"):
        return cfg["recordings"]
    return os.path.join(cfg["workspace"], "recordings") if cfg.get("workspace") else None


def group_items(items):
    """One row per recording: a clip's .mp4 and .srt (or a mark's files) together, newest first."""
    rows = {}
    for i in items:
        key = (i["source"], i["group"], i["base"])
        r = rows.setdefault(key, {"when": i["when"], "kind": i["kind"], "locked": i["locked"], "base": i["base"], "files": [],
                                  "size": 0, "pulled": True, "pulled_before": False, "busy": False})
        r["files"].append(i["name"].rsplit(".", 1)[-1])
        r["size"] += i["size"]
        r["pulled"] = r["pulled"] and i["pulled"]
        r["pulled_before"] = r["pulled_before"] or i["pulled_before"]
        r["busy"] = r["busy"] or i["busy"]
    return sorted(rows.values(), key=lambda r: (r["when"] is not None, r["when"]), reverse=True)


class RecordingsPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.loaded_once = False

        where = QGroupBox("Copies go to")
        self.dest_label = QLabel()
        self.dest_label.setWordWrap(True)
        change = QPushButton("Choose…")
        change.clicked.connect(self.choose_dest)
        self.open_btn = QPushButton(forms.SHOW_FOLDER)
        self.open_btn.clicked.connect(self.open_dest)
        row = QHBoxLayout(where)
        row.addWidget(self.dest_label, 1)
        row.addWidget(change)
        row.addWidget(self.open_btn)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Recorded", "What", "Files", "Size", "On this computer"])
        hh = self.table.horizontalHeader()
        for c in range(5):
            hh.setSectionResizeMode(c, QHeaderView.Stretch if c == 0 else QHeaderView.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.doubleClicked.connect(lambda *_: self.open_dest())
        self.table.setToolTip("Double-click to show the copies")

        self.refresh_btn = QPushButton("Check card")
        self.refresh_btn.clicked.connect(self.refresh)
        self.pull_btn = QPushButton("Sync to PC")
        self.pull_btn.setDefault(True)
        self.pull_btn.clicked.connect(self.pull)
        self.free_btn = QPushButton("Free up the card…")
        self.free_btn.setToolTip("Deletes from the card only what is safely copied here")
        self.free_btn.clicked.connect(self.free)
        self.mix_btn = QPushButton("Mix and export…")
        self.mix_btn.setToolTip("Makes a video from the selected clips with the engine and exhaust mixed into one sound")
        self.mix_btn.clicked.connect(self.mix)
        buttons = QHBoxLayout()
        for w in (self.pull_btn, self.refresh_btn, self.free_btn):
            buttons.addWidget(w)
        buttons.addStretch()
        buttons.addWidget(self.mix_btn)
        self.rows = []
        self.bar = Progress(state)
        self.bar.hide()
        self.note = QLabel()
        self.note.setWordWrap(True)

        page = QVBoxLayout(self)
        page.addWidget(where)
        empty, self.empty_text = forms.empty("No recordings on the phone", "")
        self.body = QStackedWidget()
        self.body.addWidget(self.table)
        self.body.addWidget(empty)
        page.addWidget(self.summary)
        page.addWidget(self.body, 1)
        page.addWidget(self.note)
        page.addLayout(buttons)

        state.target_changed.connect(self._target_changed)
        state.busy_changed.connect(self._buttons)
        state.busy_changed.connect(self._phone_free)
        self.show_dest()

    # ---- where copies go ----

    def dest(self):
        return recordings_dest()

    def show_dest(self):
        d = self.dest()
        self.dest_label.setText(d or "No vehicle open.")
        self.open_btn.setEnabled(bool(d))
        self._buttons()

    def choose_dest(self):
        folder = QFileDialog.getExistingDirectory(self, "Where should recordings be copied?", self.dest() or "")
        if not folder:
            return
        cfg = paths.load_config()
        cfg["recordings"] = folder
        paths.save_config(cfg)
        self.show_dest()
        self.refresh()

    def open_dest(self):
        if self.dest():
            forms.show_folder(self.dest())

    # ---- state ----

    def _ready(self):
        return bool(self.dest()) and self.state.has_target() and not self.state.busy

    def _buttons(self):
        ok = self._ready()
        for b in (self.refresh_btn, self.pull_btn, self.free_btn):
            b.setEnabled(ok)
        self.mix_btn.setEnabled(bool(self.dest()))          # works on the copies here: no phone needed
        if not self.state.has_target():
            self.note.setText("Choose a phone or card on the Phone page first.")

    def _target_changed(self):
        self.body.setCurrentIndex(0)
        self.table.setRowCount(0)
        self.summary.setText("")
        self.loaded_once = False          # looked at again the next time the page is shown
        self._buttons()
        if self.isVisible():
            self.showEvent(None)

    def _phone_free(self):
        """Shown while another job had the phone: look now that it is free."""
        if not self.state.busy and self.isVisible() and not self.loaded_once:
            self.showEvent(None)

    def showEvent(self, e):
        if e is not None:
            super().showEvent(e)
        if not self.loaded_once and self._ready():
            self.loaded_once = True
            self.refresh()

    def _start(self, text, what, bar=True):
        if not self.state.begin(what):
            return False
        self._buttons()
        self.bar.setRange(0, 0)
        self.bar.setVisible(bar)
        self.note.setText(text)
        self.state.watch(self.note)
        return True

    def _stop(self):
        self.state.end()
        self.bar.hide()
        self._buttons()

    def _sources(self):
        try:
            return self.state.sources()
        except SystemExit as e:
            self._error(str(e.code))
            return None

    # ---- list ----

    def refresh(self, after=""):
        if not self._ready():
            return
        srcs = self._sources()
        if srcs is None:
            return
        dest = self.dest()
        self.after = after
        if self._start("Looking at the card\u2026", "looking at the recordings"):
            worker.run(lambda: recordings.status(srcs, dest), self._listed, self._failed)

    def _listed(self, st):
        self._stop()
        dest = self.dest()
        rows = group_items(st["items"])
        self.rows = rows
        self.table.setRowCount(len(rows))
        for n, r in enumerate(rows):
            what = KINDS.get(r["kind"], r["kind"]) + (", locked" if r["locked"] else "")
            names = [n for n in recordings.sound_channels(dest, r["base"]) if n] if r["kind"] == "sound" else []
            if names:
                what += ": " + " / ".join(names)
            here = ("being recorded" if r["busy"] else "yes" if r["pulled"]
                    else "copied before, deleted here" if r["pulled_before"] else "not yet")
            cells = [r["when"].strftime("%a %d %b %Y  %H:%M:%S") if r["when"] else "?", what,
                     " + ".join(sorted(r["files"])), _mb(r["size"]), here]
            for c, text in enumerate(cells):
                self.table.setItem(n, c, QTableWidgetItem(text))
        new = [r for r in rows if not r["pulled"] and not r["pulled_before"] and not r["busy"]]
        total = sum(r["size"] for r in rows)
        self.body.setCurrentIndex(0 if rows else 1)
        if not rows:
            self.summary.setText("")
            self.empty_text.setText("Clips, marks and trips the app records show up here, ready to copy to this computer."
                                    if st["missing_sources"] < len(self._sources() or [1])
                                    else "The app has not recorded anything yet: there is no dashcam folder on the card.")
        else:
            self.summary.setText("%d recordings on the card (%s); %s." % (
                len(rows), _mb(total), "%d not on this computer yet (%s)" % (len(new), _mb(sum(r["size"] for r in new)))
                if new else "all of them are on this computer"))
        self.pull_btn.setEnabled(self._ready() and bool(new))
        self.note.setText(self.after)

    # ---- pull ----

    def pull(self):
        srcs = self._sources()
        if srcs is None:
            return
        dest = self.dest()
        if not self._start("Copying\u2026", "copying recordings"):
            return

        def work(report):
            return recordings.pull(srcs, dest, log=lambda m: None,
                                   progress=lambda i, n, d, t, key: report((i, n, d, t, key), None))
        worker.run(work, self._pulled, self._failed, progress=self._progress)

    def _progress(self, info, _):
        i, n, done, total, key = info
        self.bar.setRange(0, 1000)
        self.bar.setValue(int(done * 1000 / total) if total else 1000)
        self.note.setText("Copying %d of %d (%s of %s): %s" % (i, n, _mb(done), _mb(total), key))

    def _pulled(self, r):
        self._stop()
        msg = "Copied %d files (%s)." % (r["pulled"], _mb(r["bytes"]))
        if r["skipped_busy"]:
            msg += " %d still being recorded, left for next time." % r["skipped_busy"]
        self.refresh(after=msg)

    # ---- mix and export ----

    def selected_clips(self):
        """The copies here of the selected rows that are dashcam clips."""
        dest = self.dest()
        out = []
        for row in sorted({i.row() for i in self.table.selectedIndexes()}):
            r = self.rows[row] if row < len(self.rows) else None
            if r and r["kind"] == "clip" and dest:
                p = os.path.join(dest, "clips", r["base"] + ".mp4")
                if os.path.exists(p):
                    out.append(p)
        return out

    def mix(self):
        MixDialog(self, self.selected_clips(), self.dest()).exec()

    # ---- free up ----

    def free(self):
        srcs = self._sources()
        if srcs is None:
            return
        box = QMessageBox(QMessageBox.Question, "Free up the card",
                          "Delete from the card the recordings that are already copied to\n%s?\n\nOnly files whose "
                          "copy is there at the same size are removed. Anything not copied yet stays." % self.dest(),
                          QMessageBox.Yes | QMessageBox.No, self)
        locked = QCheckBox("Locked clips too (normally they stay on the card)")
        box.setCheckBox(locked)
        if box.exec() != QMessageBox.Yes:
            return
        keep_locked = not locked.isChecked()
        dest = self.dest()
        if self._start("Deleting copied recordings from the card\u2026", "freeing up the card"):
            worker.run(lambda: recordings.delete_pulled(srcs, dest, keep_locked=keep_locked, log=lambda m: None),
                       self._freed, self._failed)

    def _freed(self, r):
        self._stop()
        msg = "Deleted %d files from the card, %s freed." % (r["deleted"], _mb(r["freed"]))
        kept = []
        if r["kept_locked"]:
            kept.append("%d locked" % r["kept_locked"])
        if r["not_pulled"]:
            kept.append("%d not copied yet" % r["not_pulled"])
        if r["kept_changed"]:
            kept.append("%d changed since copying" % r["kept_changed"])
        if kept:
            msg += " Kept: " + ", ".join(kept) + "."
        self.refresh(after=msg)

    def _failed(self, msg):
        self._stop()
        self.note.setText("")
        self._error(msg)

    def _error(self, msg):
        forms.error(self, "Recordings", msg)
