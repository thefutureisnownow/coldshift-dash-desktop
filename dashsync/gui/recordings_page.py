"""Recordings page: what the dashcam left on the card and what is copied here, pull it, then free up the card
on request.

The list holds both: what the phone has and the copies on this computer (also those whose originals are gone
from the phone, and all of them when the phone is not connected). A row is shown in Finder (Explorer) with a
double-click; Mix and export takes the selected rows' videos; Delete takes the selected rows off this computer
(to the Trash), the phone, or both. Selected rows stay selected when the list is looked at again.
"""
import datetime
import os
import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QPushButton, QStackedWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import drives, paths, recordings
from . import forms, worker
from .state import Progress
from .mix_dialog import MixDialog
from .thumbs import Thumbs

KINDS = {"clip": "Clip", "mark": "Mark", "trip": "Trip log", "interior": "Interior shot", "sound": "Sound"}
# which of a row's files Show in Finder picks out, first found
SHOW_FIRST = (".mp4", ".wav", ".jpg", ".gpx", ".json", ".csv", ".srt", ".gcsv")
VIDEO_KINDS = ("clip", "mark")
COLUMNS = ["Recorded", "What", "Files", "Size", "On the phone", "On this computer"]
ICON = QSize(80, 45)
ROLE = Qt.UserRole                  # an item's ("drive", index into self.drives) or ("row", index into self.rows)


def _mb(n):
    return ("%.1f GB" % (n / 1e9) if n >= 1e9 else "%.0f MB" % (n / 1e6) if n >= 1e6
            else "%.0f KB" % (n / 1e3) if n >= 1e3 else "under 1 KB")


def _n(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else many or one + "s")


def recordings_dest():
    """Where the Recordings tab keeps its copies (the vehicle's recordings/ folder unless one was chosen)."""
    cfg = paths.load_config()
    if cfg.get("recordings"):
        return cfg["recordings"]
    return os.path.join(cfg["workspace"], "recordings") if cfg.get("workspace") else None


def group_items(items):
    """One row per recording: a clip's .mp4 and .srt (or a mark's files) together, newest first. A row keeps
    its files ("items"), and says whether they are on the card ("on_card") and here ("pulled": all of them)."""
    rows = {}
    for i in items:
        key = (i["group"], i["base"])
        r = rows.setdefault(key, {"id": key, "when": i["when"], "kind": i["kind"], "locked": i["locked"],
                                  "base": i["base"], "files": [], "items": [], "size": 0, "pulled": True,
                                  "pulled_before": False, "busy": False, "on_card": False})
        r["files"].append(i["name"].rsplit(".", 1)[-1])
        r["items"].append(i)
        r["size"] += i["size"]
        r["pulled"] = r["pulled"] and i["pulled"]
        r["pulled_before"] = r["pulled_before"] or i["pulled_before"]
        r["busy"] = r["busy"] or i["busy"]
        r["on_card"] = r["on_card"] or i.get("on_card", True)
    return sorted(rows.values(), key=lambda r: (r["when"] is not None, r["when"]), reverse=True)


def _with_drives(st, dest):
    """A listing with its rows gathered into drives (st["drives"]): done off the window's thread, since it reads
    the clips' subtitles for their lengths."""
    st["drives"] = drives.group(group_items(st["items"]), dest)
    return st


def local_path(dest, item):
    return os.path.join(dest, *item["key"].split("/"))


def shown_file(dest, row):
    """The row's file to pick out in Finder (its video, sound or photo before the rest), or None when none of
    its files is here."""
    here = [local_path(dest, i) for i in row["items"] if os.path.isfile(local_path(dest, i))]
    for ext in SHOW_FIRST:
        for p in here:
            if p.lower().endswith(ext):
                return p
    return here[0] if here else None


def videos(dest, rows):
    """The selected rows' videos (dashcam clips and marks' .mp4): (paths here, items only on the phone)."""
    here, missing = [], []
    for r in rows:
        if r["kind"] not in VIDEO_KINDS:
            continue
        for i in r["items"]:
            if not i["name"].lower().endswith(".mp4"):
                continue
            if os.path.isfile(local_path(dest, i)):
                here.append(local_path(dest, i))
            elif i.get("on_card", True) and not i["busy"]:
                missing.append(i)
    return here, missing


class DeleteDialog(QDialog):
    """Asks where to delete the selected recordings from: this computer (to the Trash), the phone, or both."""
    def __init__(self, parent, rows, dest, phone_ok):
        super().__init__(parent)
        self.setWindowTitle("Delete recordings")
        self.here = [i for r in rows for i in r["items"] if os.path.isfile(local_path(dest, i))]
        self.card = [i for r in rows for i in r["items"] if i.get("on_card", True)]
        self.locked = any(r["locked"] for r in rows)
        what = ("the %s of %s" % (KINDS.get(rows[0]["kind"], "recording").lower(),
                                  rows[0]["when"].strftime("%a %d %b %Y %H:%M:%S")) if len(rows) == 1 and rows[0]["when"]
                else _n(len(rows), "recording"))
        head = QLabel("Delete %s from:" % what)
        head.setWordWrap(True)
        here_bytes = sum(os.path.getsize(local_path(dest, i)) for i in self.here)
        self.cb_here = QCheckBox("This computer: %s, %s (moved to %s)" % (_n(len(self.here), "file"), _mb(here_bytes),
                                                                         forms.TRASH)
                                 if self.here else "This computer (it has no copy)")
        self.cb_here.setEnabled(bool(self.here))
        self.cb_here.setChecked(bool(self.here))
        card_text = ("The phone: %s, %s (gone for good)" % (_n(len(self.card), "file"), _mb(sum(i["size"] for i in self.card)))
                     if self.card else "The phone (it doesn't have them any more)")
        if self.card and not phone_ok:
            card_text = "The phone: connect it first (or wait for the job that has it)"
        self.cb_card = QCheckBox(card_text)
        self.cb_card.setEnabled(bool(self.card) and phone_ok)
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color: %s" % forms.WARN)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.delete_btn = self.buttons.addButton("Delete", QDialogButtonBox.DestructiveRole)
        self.delete_btn.clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(head)
        lay.addWidget(self.cb_here)
        lay.addWidget(self.cb_card)
        lay.addWidget(self.warn)
        lay.addWidget(self.buttons)
        for cb in (self.cb_here, self.cb_card):
            cb.toggled.connect(self._changed)
        self._changed()

    def _changed(self, *_):
        here, card = self.cb_here.isChecked(), self.cb_card.isChecked()
        self.delete_btn.setEnabled(here or card)
        words = []
        if card:
            only_there = [i for i in self.card if not i["pulled"]]
            if here:
                words.append("They'll be on neither: what was on the phone is gone for good, and this computer's "
                             "copies can only be brought back from %s." % forms.TRASH)
            elif only_there:
                words.append("%s on the phone %s no copy here: deleting from the phone loses %s."
                             % (_n(len(only_there), "file"), "has" if len(only_there) == 1 else "have",
                                "it" if len(only_there) == 1 else "them"))
            if self.locked:
                words.append("Locked clips are among them.")
        self.warn.setText(" ".join(words))
        self.warn.setVisible(bool(words))


class RecordingsPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.loaded_once = False
        self.listed_phone = False         # the last list included the phone's files
        self.after = ""
        self.loud = False                 # the user asked for this look: a phone that can't be reached is an error
        self.then_mix = None              # keys to mix once copied
        self.mine = False                 # this page's job holds the phone

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
        self.table = QTreeWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHeaderLabels(COLUMNS)
        hh = self.table.header()
        hh.setStretchLastSection(False)
        for c in range(len(COLUMNS)):
            hh.setSectionResizeMode(c, QHeaderView.Stretch if c == 0 else QHeaderView.ResizeToContents)
        self.table.setIconSize(ICON)
        self.table.setUniformRowHeights(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setExpandsOnDoubleClick(True)
        self.table.itemDoubleClicked.connect(self._double_clicked)
        self.table.setToolTip("A drive is a run of recordings with no long gap; select it to take all of them.\n"
                              "Double-click a recording: %s. Right-click for more." % forms.SHOW_FILE)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemSelectionChanged.connect(self._buttons)
        self.table.itemExpanded.connect(lambda it: self._opened(it, True))
        self.table.itemCollapsed.connect(lambda it: self._opened(it, False))
        self.drives = []
        self.open_drives = None           # ids of the drives shown open (None: the newest, at first)
        self.row_items = {}               # row id -> its tree item, for pictures as they come
        self.row_index = {}               # row id -> its index in self.rows
        self.thumbs = Thumbs(self)
        self.thumbs.ready.connect(self._thumb_ready)

        self.refresh_btn = QPushButton("Check card")
        self.refresh_btn.clicked.connect(lambda: self.refresh(loud=True))
        self.pull_btn = QPushButton("Sync to PC")
        self.pull_btn.setDefault(True)
        self.pull_btn.clicked.connect(lambda: self.pull())
        self.free_btn = QPushButton("Free up the card…")
        self.free_btn.setToolTip("Deletes from the card only what is safely copied here")
        self.free_btn.clicked.connect(self.free)
        self.delete_btn = QPushButton("Delete…")
        self.delete_btn.setToolTip("Deletes the selected recordings from this computer, the phone, or both")
        self.delete_btn.clicked.connect(self.delete)
        self.mix_btn = QPushButton("Mix and export…")
        self.mix_btn.setToolTip("Makes a video from the selected clips with the engine and exhaust mixed into one sound")
        self.mix_btn.clicked.connect(self.mix)
        buttons = QHBoxLayout()
        for w in (self.pull_btn, self.refresh_btn, self.free_btn):
            buttons.addWidget(w)
        buttons.addStretch()
        buttons.addWidget(self.delete_btn)
        buttons.addWidget(self.mix_btn)
        self.rows = []
        self.bar = Progress(state)
        self.bar.hide()
        self.note = QLabel()
        self.note.setWordWrap(True)

        page = QVBoxLayout(self)
        page.addWidget(where)
        empty, self.empty_text = forms.empty("No recordings yet", "")
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
        """The phone (or card) can be used now."""
        return bool(self.dest()) and self.state.has_target() and not self.state.busy

    def _buttons(self):
        ok = self._ready()
        for b in (self.refresh_btn, self.pull_btn, self.free_btn):
            b.setEnabled(ok)
        chosen = bool(self.selected_rows())
        self.mix_btn.setEnabled(bool(self.dest()))          # works on the copies here: no phone needed
        self.delete_btn.setEnabled(bool(self.dest()) and chosen and not self.state.busy)

    def _target_changed(self):
        self.body.setCurrentIndex(0)
        self.table.clear()
        self.rows, self.drives, self.row_items = [], [], {}
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
        if not self.loaded_once and self.dest() and not self.state.busy:
            self.loaded_once = True
            self.refresh()

    def _start(self, text, what, bar=True):
        if not self.state.begin(what):
            return False
        self.mine = True
        self._buttons()
        self.bar.setRange(0, 0)
        self.bar.setVisible(bar)
        self.note.setText(text)
        self.state.watch(self.note)
        return True

    def _stop(self):
        if self.mine:                     # only a job this page started holds the phone
            self.mine = False
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

    def refresh(self, after="", loud=False):
        """Looks at the phone and this computer, or with no phone chosen (or the phone busy with another job)
        at this computer alone. A phone that can't be reached shows what is here, and says why."""
        dest = self.dest()
        if not dest:
            return
        self.after, self.loud = after, loud
        if not self._ready():
            if self.state.busy:
                return                    # looked at once the phone is free (_phone_free)
            worker.run(lambda: _with_drives(dict(recordings.status([], dest, here_too=True), phone=False), dest),
                       self._listed, self._failed)
            return
        state = self.state
        if self._start("Looking at the card…", "looking at the recordings"):
            def work():
                try:
                    st = dict(recordings.status(state.sources(), dest, here_too=True), phone=True)
                except (Exception, SystemExit) as e:    # unplugged, asleep, card gone: what is here can still be shown
                    why = str(e.code if isinstance(e, SystemExit) else e) or "it stopped"
                    st = dict(recordings.status([], dest, here_too=True), phone=False, error=why)
                return _with_drives(st, dest)
            worker.run(work, self._listed, self._failed)

    def selected_rows(self):
        """The rows selected, and all of each selected drive's, in the list's order."""
        picked = set()
        for it in self.table.selectedItems():
            kind, n = it.data(0, ROLE)
            if kind == "row":
                picked.add(n)
            elif n < len(self.drives):
                picked.update(self.row_index[r["id"]] for r in self.drives[n]["rows"])
        return [self.rows[n] for n in sorted(picked) if n < len(self.rows)]

    def _opened(self, item, is_open):
        kind, n = item.data(0, ROLE)
        if kind == "drive" and n < len(self.drives) and self.open_drives is not None:
            (self.open_drives.add if is_open else self.open_drives.discard)(self.drives[n]["id"])

    def _double_clicked(self, item, _col):
        kind, n = item.data(0, ROLE)
        if kind == "row":
            self.reveal(n)

    def _listed(self, st):
        self._stop()
        dest = self.dest()
        keep_rows = {r["id"] for r in self.selected_rows()}
        keep_drives = {self.drives[it.data(0, ROLE)[1]]["id"] for it in self.table.selectedItems()
                       if it.data(0, ROLE)[0] == "drive" and it.data(0, ROLE)[1] < len(self.drives)}
        ds = st["drives"]
        rows = [r for d in ds for r in d["rows"]]           # newest drive first, newest row first in each
        self.rows, self.drives, self.row_items = rows, ds, {}
        self.row_index = {r["id"]: n for n, r in enumerate(rows)}
        self.listed_phone = st.get("phone", False)
        if self.open_drives is None and ds:
            self.open_drives = {ds[0]["id"]}
        self.table.blockSignals(True)
        self.table.clear()
        index = {id(r): n for n, r in enumerate(rows)}
        bold = QFont(self.table.font())
        bold.setBold(True)
        pictures = []
        for dn, d in enumerate(ds):
            top = QTreeWidgetItem(self._drive_cells(d))
            top.setData(0, ROLE, ("drive", dn))
            for c in range(len(COLUMNS)):
                top.setFont(c, bold)
            self.table.addTopLevelItem(top)
            for r in d["rows"]:
                n = index[id(r)]
                it = QTreeWidgetItem(self._row_cells(r, dest))
                it.setData(0, ROLE, ("row", n))
                it.setSizeHint(0, QSize(0, ICON.height() + 4))
                top.addChild(it)
                self.row_items[r["id"]] = it
                src = self._picture_of(r, dest)
                icon = self.thumbs.icon(src) if src else None
                it.setIcon(0, icon or self._blank())           # (a blank keeps the times in line)
                if src:
                    pictures.append(src)
                if r["id"] in keep_rows and d["id"] not in keep_drives:
                    it.setSelected(True)
            cover = self._cover(d, dest)
            if cover and self.thumbs.icon(cover):
                top.setIcon(0, self.thumbs.icon(cover))
            top.setSizeHint(0, QSize(0, ICON.height() + 4))
            top.setExpanded(d["id"] in self.open_drives)
            if d["id"] in keep_drives:
                top.setSelected(True)
        self.table.blockSignals(False)
        self.thumbs.want(pictures)
        self._buttons()
        on_card = [r for r in rows if r["on_card"]]
        new = [r for r in on_card if not r["pulled"] and not r["pulled_before"] and not r["busy"]]
        only_here = [r for r in rows if not r["on_card"]]
        self.body.setCurrentIndex(0 if rows else 1)
        if not rows:
            self.summary.setText("")
            self.empty_text.setText("Clips, marks and trips the app records show up here, ready to copy to this computer."
                                    if not self.listed_phone or st["missing_sources"] < len(self.state.sources() if
                                                                                            self.state.has_target() else [1])
                                    else "The app has not recorded anything yet: there is no dashcam folder on the card.")
        elif self.listed_phone:
            text = "%s on the card (%s); %s." % (
                _n(len(on_card), "recording"), _mb(sum(r["size"] for r in on_card)),
                "%d not on this computer yet (%s)" % (len(new), _mb(sum(r["size"] for r in new))) if new
                else "all of them are on this computer")
            if only_here:
                text += " %s only on this computer." % _n(len(only_here), "more", "more")
            self.summary.setText(text)
        else:
            self.summary.setText("%s on this computer (%s)." % (_n(len(rows), "recording"), _mb(sum(r["size"] for r in rows))))
        self.pull_btn.setEnabled(self._ready() and bool(new))
        note = self.after
        if not self.state.has_target():
            note = "Choose a phone or card on the Phone page to see what it holds too. " + note
        if st.get("error"):
            note = ("Couldn't look at the phone (%s), so this is what is on this computer. " % st["error"].strip()) + note
            if self.loud:
                self._error(st["error"])
        self.note.setText(note.strip())
        then, self.then_mix = self.then_mix, None
        if then is not None:
            self._mix_paths([p for p in (os.path.join(dest, *k.split("/")) for k in then if k.lower().endswith(".mp4"))
                             if os.path.isfile(p)])

    # ---- one row ----

    def _drive_cells(self, d):
        rows = d["rows"]
        if d["start"] is None:
            when = "Undated"
        else:
            a = rows[-1]["when"]
            b = datetime.datetime.fromtimestamp(d["end"])
            when = "%s  %s\u2013%s" % (a.strftime("%a %d %b %Y"), a.strftime("%H:%M"), b.strftime("%H:%M"))
        counts = {}
        for r in rows:
            counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        names = {"clip": "clip", "mark": "mark", "trip": "trip log", "interior": "interior shot", "sound": "sound recording"}
        what = ", ".join(_n(counts[k], names.get(k, k)) for k in ("clip", "mark", "sound", "interior", "trip", "tests")
                         if k in counts)
        on_card = sum(1 for r in rows if r["on_card"])
        here = sum(1 for r in rows if r["pulled"])
        phone = ("\u2014" if not self.listed_phone else "yes" if on_card == len(rows) else "no" if not on_card
                 else "%d of %d" % (on_card, len(rows)))
        mine = "yes" if here == len(rows) else "not yet" if not here else "%d of %d" % (here, len(rows))
        return [when, what, "", _mb(sum(r["size"] for r in rows)), phone, mine]

    def _row_cells(self, r, dest):
        what = KINDS.get(r["kind"], r["kind"]) + (", locked" if r["locked"] else "")
        names = [n for n in recordings.sound_channels(dest, r["base"]) if n] if r["kind"] == "sound" else []
        if names:
            what += ": " + " / ".join(names)
        here = ("being recorded" if r["busy"] else "yes" if r["pulled"]
                else "copied before, deleted here" if r["pulled_before"] else "not yet")
        phone = ("yes" if r["on_card"] else "no") if self.listed_phone else "\u2014"
        return [r["when"].strftime("%H:%M:%S") if r["when"] else "?", what,
                " + ".join(sorted(r["files"])), _mb(r["size"]), phone, here]

    def _blank(self):
        if not hasattr(self, "_blank_icon"):
            pm = QPixmap(ICON)
            pm.fill(Qt.transparent)
            self._blank_icon = QIcon(pm)
        return self._blank_icon

    @staticmethod
    def _picture_of(r, dest):
        """The file here whose small picture the row shows: a video's or a photo's."""
        for i in r["items"]:
            p = local_path(dest, i)
            if i["name"].lower().endswith((".mp4", ".jpg")) and os.path.isfile(p):
                return p
        return None

    def _cover(self, d, dest):
        """The picture a drive shows: its middle clip's (the first is often still parked)."""
        pics = [p for p in (self._picture_of(r, dest) for r in d["rows"] if r["kind"] == "clip") if p]
        pics = pics or [p for p in (self._picture_of(r, dest) for r in d["rows"]) if p]
        return pics[len(pics) // 2] if pics else None

    def _thumb_ready(self, src):
        icon = self.thumbs.icon(src)
        if not icon:
            return
        dest = self.dest()
        for r in self.rows:
            if self._picture_of(r, dest) == src and r["id"] in self.row_items:
                self.row_items[r["id"]].setIcon(0, icon)
        for dn, d in enumerate(self.drives):
            if self._cover(d, dest) == src:
                top = self.table.topLevelItem(dn)
                if top:
                    top.setIcon(0, icon)

    def _menu(self, pos):
        item = self.table.itemAt(pos)
        if item is None:
            return
        kind, n = item.data(0, ROLE)
        rows = self.selected_rows()
        menu = QMenu(self)
        show = menu.addAction(forms.SHOW_FILE)
        show.setEnabled(kind == "row" and bool(shown_file(self.dest(), self.rows[n])))
        show.triggered.connect(lambda: self.reveal(n))
        mix = menu.addAction("Mix and export…")
        mix.setEnabled(any(r["kind"] in VIDEO_KINDS for r in rows))
        mix.triggered.connect(self.mix)
        menu.addSeparator()
        delete = menu.addAction("Delete…")
        delete.setEnabled(self.delete_btn.isEnabled())
        delete.triggered.connect(self.delete)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def reveal(self, n):
        """Picks out the row's file in Finder (Explorer); the folder when it isn't on this computer."""
        if not 0 <= n < len(self.rows) or not self.dest():
            return
        p = shown_file(self.dest(), self.rows[n])
        if p:
            forms.reveal(p)
        else:
            self.note.setText("That one isn't on this computer%s." % (": Sync to PC copies it" if self.rows[n]["on_card"] else ""))

    # ---- pull ----

    def pull(self, only=None):
        srcs = self._sources()
        if srcs is None:
            return
        dest = self.dest()
        if not self._start("Copying…", "copying recordings"):
            return

        def work(report):
            return recordings.pull(srcs, dest, log=lambda m: None, only=only,
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
        """The copies here of the selected rows' videos (dashcam clips and marks)."""
        return videos(self.dest(), self.selected_rows())[0] if self.dest() else []

    def mix(self):
        dest = self.dest()
        rows = self.selected_rows()
        if not rows:
            box = QMessageBox(QMessageBox.Information, "Mix and export",
                              "Select the clips to mix in the list first: click one, and Shift-click or %s-click "
                              "to add more." % ("⌘" if sys.platform == "darwin" else "Ctrl"), QMessageBox.Ok, self)
            choose = box.addButton("Choose files…", QMessageBox.ActionRole)
            box.exec()
            if box.clickedButton() is choose:
                MixDialog(self, [], dest).exec()
            return
        here, missing = videos(dest, rows)
        if not here and not missing:
            QMessageBox.information(self, "Mix and export", "Mix and export makes videos from dashcam clips and "
                                    "marks; none is selected.")
            return
        if missing:
            if not self._ready():
                if not here:
                    QMessageBox.information(self, "Mix and export", "The selected clips aren't on this computer yet. "
                                            "Connect the phone and Sync to PC first.")
                    return
            else:
                ans = QMessageBox.question(
                    self, "Mix and export", "%s of the selected clips %s on the phone only. Copy %s here first?"
                    % (len(missing), "is" if len(missing) == 1 else "are", "it" if len(missing) == 1 else "them"),
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
                if ans == QMessageBox.Cancel:
                    return
                if ans == QMessageBox.Yes:
                    # the whole recording comes: a clip's .srt and .gcsv with its .mp4
                    need = {(i["group"], i["base"]) for i in missing}
                    keys = [i["key"] for r in rows if r["id"] in need for i in r["items"]
                            if i.get("on_card", True) and not i["pulled"]]
                    self.then_mix = keys + [os.path.relpath(p, dest).replace(os.sep, "/") for p in here]
                    self.pull(only=set(keys))
                    if not self.state.busy:     # it didn't start
                        self.then_mix = None
                    return
        self._mix_paths(here)

    def _mix_paths(self, clips):
        if clips:
            MixDialog(self, clips, self.dest()).exec()

    # ---- delete ----

    def delete(self):
        rows = [r for r in self.selected_rows() if not r["busy"]]
        dest = self.dest()
        if not rows or not dest:
            if self.selected_rows():
                self.note.setText("A recording still being made can't be deleted.")
            return
        dlg = DeleteDialog(self, rows, dest, phone_ok=self._ready() and self.listed_phone)
        if dlg.exec() != QDialog.Accepted:
            return
        here = [i["key"] for i in dlg.here] if dlg.cb_here.isChecked() else []
        card = list(dlg.card) if dlg.cb_card.isChecked() else []
        srcs = self._sources() if card else []
        if srcs is None:
            return

        def work():
            out = {"here": recordings.delete_here(dest, here, remove=forms.to_trash) if here else None}
            out["card"] = recordings.delete_from_card(srcs, card) if card else None
            return out
        if card:
            if not self._start("Deleting from the phone…", "deleting recordings"):
                return
        worker.run(work, self._deleted, self._failed)

    def _deleted(self, r):
        self._stop()
        msg = []
        if r["here"]:
            msg.append("Moved %s (%s) to %s." % (_n(r["here"]["deleted"], "file"), _mb(r["here"]["freed"]), forms.TRASH))
        if r["card"]:
            msg.append("Deleted %s from the phone, %s freed." % (_n(r["card"]["deleted"], "file"), _mb(r["card"]["freed"])))
            if r["card"]["kept_changed"]:
                msg.append("%s changed since the list was made, so %s kept."
                           % (_n(r["card"]["kept_changed"], "file"), "it was" if r["card"]["kept_changed"] == 1 else "they were"))
        self.refresh(after=" ".join(msg))

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
        if self._start("Deleting copied recordings from the card…", "freeing up the card"):
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
        self.then_mix = None
        self._error(msg)

    def _error(self, msg):
        forms.error(self, "Recordings", msg)
