"""Voices page: the voice packs for navigation prompts. Pick one to see the lines it needs, play them,
and add a recording (an MP3 file) for each; then put the packs on the card. Angie, built into the app,
is listed as a reference for how the lines sound and can be the start of a new pack."""
import os

from PySide6.QtCore import QFile, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .. import paths, voice
from . import forms, sound, worker
from .syncbar import SyncBar

FOLDER, KEY = Qt.UserRole, Qt.UserRole + 1
AUDIO_FILTER = "Audio (*.mp3 *.wav *.ogg *.m4a)"


class NewVoiceDialog(QDialog):
    def __init__(self, parent, can_copy):
        super().__init__(parent)
        self.setWindowTitle("New voice")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name, as the app shows it")
        self.copy = QCheckBox("Start with copies of Angie's lines, to replace one at a time")
        self.copy.setVisible(can_copy)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("A voice pack holds one recording for each line the app says."))
        lay.addWidget(self.name)
        lay.addWidget(self.copy)
        lay.addWidget(buttons)


class LineTree(QTreeWidget):
    """The lines, grouped; an audio file dropped on a line is added for it."""
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)

    def _file(self, e):
        urls = e.mimeData().urls() if e.mimeData().hasUrls() else []
        return urls[0].toLocalFile() if len(urls) == 1 and urls[0].toLocalFile().lower().endswith(voice.FORMATS) else None

    def dragEnterEvent(self, e):
        if self._file(e) and self.page.editable():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        if self._file(e) and item is not None and item.data(0, KEY):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        path = self._file(e)
        if path and item is not None and item.data(0, KEY):
            self.page.add_recording(item.data(0, KEY), path)
            e.acceptProposedAction()


class VoicesPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state

        left = QWidget()
        self.packs = QListWidget()
        self.packs.currentItemChanged.connect(lambda *_: self.show_pack())
        self.new_btn = QPushButton("New…")
        self.import_btn = QPushButton("Import…")
        self.export_btn = QPushButton("Export…")
        self.rename_btn = QPushButton("Rename…")
        self.delete_btn = QPushButton("Delete")
        self.new_btn.clicked.connect(self.new_pack)
        self.import_btn.clicked.connect(self.import_pack)
        self.export_btn.clicked.connect(self.export_pack)
        self.rename_btn.clicked.connect(self.rename_pack)
        self.delete_btn.clicked.connect(self.delete_pack)
        self.import_btn.setToolTip("Add a voice pack someone shared (a .zip)")
        self.export_btn.setToolTip("Save the voice pack as a .zip to share")
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        for b in (self.new_btn, self.import_btn, self.export_btn):
            row1.addWidget(b)
        for b in (self.rename_btn, self.delete_btn):
            row2.addWidget(b)
        row2.addStretch()
        self.sync_note = forms.note("")
        ws_now = lambda: self.workspace()
        self.syncbar = SyncBar(
            state, "syncing voices",
            lambda t: (lambda r: r["copied"] + r["removed"])(voice.sync(t, ws_now(), dry_run=True)),
            lambda t: voice.sync(t, ws_now()),
            lambda r: "On the card: %s. %s" % (
                ", ".join(r["packs"]) or "only the built-in voice",
                "Choose the voice on the phone: Settings \u2192 Voice prompts while navigating." if r["packs"]
                else ""))
        box = QGroupBox("Voices")
        lay = QVBoxLayout(box)
        lay.addWidget(self.packs, 1)
        lay.addLayout(row1)
        lay.addLayout(row2)
        lay2 = QVBoxLayout(left)
        lay2.setContentsMargins(0, 0, 0, 0)
        lay2.addWidget(box, 1)
        lay2.addWidget(self.sync_note)

        right = QWidget()
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 16px; font-weight: 600")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.sample_btn = QPushButton("▶ Play a prompt")
        self.sample_btn.setToolTip("“In two hundred metres, turn left. Then turn right.”, as the app joins the lines")
        self.sample_btn.clicked.connect(self.play_sample)
        self.stop_btn = QPushButton("\u25a0 Stop")
        self.stop_btn.clicked.connect(sound.stop)
        head = QHBoxLayout()
        head.addWidget(self.title, 1)
        head.addWidget(self.sample_btn)
        head.addWidget(self.stop_btn)
        self.banner = QWidget()
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(QLabel("Angie is built into the app and can't be changed; a new voice can start from her lines."), 1)
        from_angie = QPushButton("New voice from Angie\u2026")
        from_angie.clicked.connect(lambda: self.new_pack(from_angie=True))
        bl.addWidget(from_angie)
        self.tree = LineTree(self)
        self.tree.setHeaderLabels(["Line", "Recording"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setRootIsDecorated(True)
        self.tree.itemSelectionChanged.connect(self._buttons)
        self.tree.itemDoubleClicked.connect(lambda item, _: self.play_line())
        self.play_btn = QPushButton("▶ Play")
        self.add_btn = QPushButton("Add recording…")
        self.remove_btn = QPushButton("Remove recording")
        self.play_btn.clicked.connect(self.play_line)
        self.add_btn.clicked.connect(lambda: self.add_recording(self._key()))
        self.remove_btn.clicked.connect(self.remove_recording)
        row = QHBoxLayout()
        for b in (self.play_btn, self.add_btn, self.remove_btn):
            row.addWidget(b)
        row.addStretch()
        self.hint = forms.note("")
        lay = QVBoxLayout(right)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(head)
        lay.addWidget(self.banner)
        lay.addWidget(self.status)
        lay.addWidget(self.tree, 1)
        lay.addLayout(row)
        lay.addWidget(self.hint)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([300, 640])
        page = QVBoxLayout(self)
        page.addWidget(split, 1)
        page.addWidget(self.syncbar)

        state.target_changed.connect(self._buttons)
        self.load()

    # ---- the packs ----

    def workspace(self):
        return paths.load_config().get("workspace")

    def showEvent(self, e):
        super().showEvent(e)
        self.load(self._folder())
        self.syncbar.recheck()

    def hideEvent(self, e):
        super().hideEvent(e)
        sound.stop()

    def load(self, select=None):
        self.packs.blockSignals(True)
        self.packs.clear()
        builtin = voice.builtin_dir()
        if builtin:
            m = voice.read_pack(builtin)
            self._add_item(m, builtin, "built into the app \u00b7 can't be changed", True)
        ws = self.workspace()
        problems = []
        if ws:
            root = voice.packs_dir(ws)
            for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
                folder = os.path.join(root, name)
                if not os.path.exists(os.path.join(folder, "voice.json")):
                    continue
                try:
                    m = voice.read_pack(folder)
                except (OSError, ValueError) as e:
                    problems.append(str(e))
                    continue
                done, total = voice.recorded(m)
                self._add_item(m, folder, "%d of %d lines recorded" % (done, total), False)
        self.packs.blockSignals(False)
        rows = [self.packs.item(i) for i in range(self.packs.count())]
        pick = [it for it in rows if it.data(FOLDER) == select] or [it for it in rows if not it.data(KEY)] or rows
        if pick:
            self.packs.setCurrentItem(pick[0])
        self.show_pack()
        notes = []
        if not ws:
            notes.append("Open a vehicle first; its voice packs are kept in its folder.")
        notes += ["Skipped: " + p for p in problems]
        self.sync_note.setText(" ".join(notes))

    def _add_item(self, meta, folder, sub, builtin):
        it = QListWidgetItem("%s\n%s" % (meta["name"], sub))
        it.setData(FOLDER, folder)
        it.setData(KEY, builtin)            # True: the built-in pack, read-only
        self.packs.addItem(it)

    def _folder(self):
        it = self.packs.currentItem()
        return it.data(FOLDER) if it else None

    def editable(self):
        it = self.packs.currentItem()
        return bool(it) and not it.data(KEY)

    def show_pack(self):
        self.tree.clear()
        folder = self._folder()
        if not folder:
            self.title.setText("No voice packs yet")
            self.status.setText("Press New to start one, or Import a pack someone shared.")
            self._buttons()
            return
        m = voice.read_pack(folder)
        done, total = voice.recorded(m)
        self.title.setText(m["name"])
        self.banner.setVisible(not self.editable())
        if not self.editable():
            self.status.setText("Used unless Settings on the phone picks another voice. Play its lines to hear how "
                                "each should sound.")
        elif done == total:
            self.status.setText("All %d lines recorded." % total)
        else:
            self.status.setText("%d of %d lines recorded. The app says nothing for the missing ones, so a prompt "
                                "can come out incomplete until they are added." % (done, total))
        bold = QFont()
        bold.setBold(True)
        muted = self.palette().color(QPalette.PlaceholderText)
        for title, advice, keys in voice.GROUPS:
            done_here = sum(1 for k in keys if k in m["lines"])
            g = QTreeWidgetItem([title, "%d of %d" % (done_here, len(keys))])
            g.setFont(0, bold)
            g.setFlags(Qt.ItemIsEnabled)
            g.setToolTip(0, advice)
            self.tree.addTopLevelItem(g)
            a = QTreeWidgetItem(g, [advice, ""])
            a.setFlags(Qt.ItemIsEnabled)
            a.setForeground(0, QBrush(muted))
            a.setFirstColumnSpanned(True)
            for key in keys:
                f = m["lines"].get(key)
                secs = voice.duration(os.path.join(folder, f)) if f else None
                it = QTreeWidgetItem(g, ["\u201c%s\u201d" % voice.LINES[key], "%.1f s" % secs if f and secs else
                                         "recorded" if f else "not recorded"])
                it.setData(0, KEY, key)
                it.setToolTip(0, key)
                if not f:
                    it.setForeground(1, QBrush(QColor(forms.WARN)))
            g.setExpanded(True)
        self.hint.setText("Drop an audio file on a line to add it. Record each line on its own with a little "
                          "silence around it, at the same distance from the microphone; MP3 is best "
                          "(WAV, Ogg and M4A work too), up to %d seconds." % voice.MAX_SECONDS
                          if self.editable() else "")
        self._buttons()

    def _key(self):
        items = self.tree.selectedItems()
        return items[0].data(0, KEY) if items else None

    def _line_file(self, key):
        folder = self._folder()
        if not folder or not key:
            return None
        f = voice.read_pack(folder)["lines"].get(key)
        return os.path.join(folder, f) if f else None

    def _buttons(self):
        ws, edit, key = self.workspace(), self.editable(), self._key()
        has = bool(self._line_file(key)) if key else False
        self.new_btn.setEnabled(bool(ws))
        self.import_btn.setEnabled(bool(ws))
        self.export_btn.setEnabled(edit)
        self.rename_btn.setEnabled(edit)
        self.delete_btn.setEnabled(edit)
        self.play_btn.setEnabled(has and sound.available())
        self.add_btn.setEnabled(edit and bool(key))
        self.remove_btn.setEnabled(edit and has)
        self.sample_btn.setEnabled(bool(self._folder()) and sound.available())
        self.stop_btn.setEnabled(sound.available())

    def new_pack(self, from_angie=False):
        d = NewVoiceDialog(self, bool(voice.builtin_dir()))
        d.copy.setChecked(from_angie)
        if d.exec() != QDialog.Accepted:
            return
        try:
            folder = voice.create(self.workspace(), d.name.text(), voice.builtin_dir() if d.copy.isChecked() else None)
        except (OSError, ValueError) as e:
            self._error(str(e))
            return
        self.load(folder)

    def import_pack(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import a voice pack", "", "Voice pack (*.zip)")
        if not path:
            return
        try:
            m = voice.install(path, self.workspace())
        except (OSError, ValueError) as e:
            self._error(str(e))
            return
        self.load(os.path.join(voice.packs_dir(self.workspace()), m["id"]))

    def export_pack(self):
        folder = self._folder()
        m = voice.read_pack(folder)
        path, _ = QFileDialog.getSaveFileName(self, "Export the voice pack", m["id"] + ".zip", "Voice pack (*.zip)")
        if path:
            voice.export(folder, path)
            self.sync_note.setText("Saved %s; send it to whoever wants the voice (they add it with Import)."
                                   % os.path.basename(path))

    def rename_pack(self):
        folder = self._folder()
        name, ok = QInputDialog.getText(self, "Rename", "Name, as the app shows it:", text=voice.read_pack(folder)["name"])
        if ok:
            try:
                voice.rename(folder, name)
            except ValueError as e:
                self._error(str(e))
            self.load(folder)

    def delete_pack(self):
        folder = self._folder()
        m = voice.read_pack(folder)
        if QMessageBox.question(self, "Delete", "Move the voice %s and its %d recordings to the Trash? The next "
                                "Sync to card removes it from the phone too." % (m["name"], len(m["lines"]))) != QMessageBox.Yes:
            return
        voice.read_pack(folder)                       # only ever a pack folder
        if not QFile.moveToTrash(folder)[0]:
            voice.delete(folder)
        self.load()
        self.syncbar.recheck()

    # ---- lines ----

    def play_line(self):
        path = self._line_file(self._key())
        if path:
            sound.play(path)

    def play_sample(self):
        files = [self._line_file(k) for k in voice.SAMPLE]
        sound.play([f for f in files if f])

    def add_recording(self, key, path=None):
        if not key or not self.editable():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Recording for “%s”" % voice.LINES[key], "", AUDIO_FILTER)
            if not path:
                return
        folder = self._folder()
        try:
            voice.set_line(folder, key, path)
        except (OSError, ValueError) as e:
            self._error(str(e))
            return
        self.load(folder)
        self._select(key)
        self.play_line()
        self.syncbar.recheck()

    def _select(self, key):
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            for j in range(g.childCount()):
                if g.child(j).data(0, KEY) == key:
                    self.tree.setCurrentItem(g.child(j))
                    return

    def remove_recording(self):
        key, folder = self._key(), self._folder()
        voice.remove_line(folder, key)
        self.load(folder)
        self._select(key)
        self.syncbar.recheck()

    def _error(self, msg):
        forms.error(self, "Voices", msg)
