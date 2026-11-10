"""Maps page: pick a region from the Mapsforge server, see where it stands, sync it to the card."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import layout, maps, paths, places, routing, search
from . import forms, worker
from .state import Progress
from .place_dialog import PlaceDialog

PATH = Qt.UserRole


def _mb(n):
    return "%.0f MB" % (n / 1024 / 1024) if n else ""


SMALL = {"and", "da", "de", "of", "the", "del", "la"}


def region_name(slug):
    """ "south-africa-and-lesotho" -> "South Africa and Lesotho"."""
    words = slug.replace("-", " ").split()
    return " ".join(w if i and w in SMALL else w.capitalize() for i, w in enumerate(words))


def _day(dt):
    return dt.strftime("%d %b %Y") if dt else "?"


class RegionDialog(QDialog):
    """The server's list of regions, with a search; accepted with `path`, the region picked."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Choose a region")
        self.path = None
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search, e.g. south africa")
        self.search.textChanged.connect(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Region", "Size"])
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._selection)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.reload_btn = QPushButton("Reload list from server")
        self.reload_btn.clicked.connect(self._reload)
        self.use_btn = QPushButton("Use this region")
        self.use_btn.setDefault(True)
        self.use_btn.clicked.connect(self.use)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(self.reload_btn)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(self.use_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(forms.note("One region per vehicle: its map, routing and place search all come from it."))
        lay.addWidget(self.search)
        lay.addWidget(self.tree, 1)
        lay.addLayout(row)
        self.resize(560, 620)
        self.load()
        self.search.setFocus()

    def _reload(self):
        self.load(refresh=True)

    def _double_clicked(self, *_):
        self.use()

    def use(self):
        path = self._selected()
        if path:
            self.path = path
            self.accept()

    # ---- the server's list ----

    def load(self, refresh=False):
        self.tree.clear()
        self.tree.addTopLevelItem(QTreeWidgetItem(["loading the map list…"]))
        self.reload_btn.setEnabled(False)
        worker.run(lambda: maps.catalog(refresh), self._fill, self._failed_list)

    def _failed_list(self, msg):
        self.tree.clear()
        self.tree.addTopLevelItem(QTreeWidgetItem(["could not load the list: " + msg]))
        self.reload_btn.setEnabled(True)

    def _fill(self, entries):
        self.reload_btn.setEnabled(True)
        self.tree.clear()
        folders = {}
        chosen = maps.chosen()

        def folder(path):
            if not path:
                return None
            if path not in folders:
                parent_path, _, name = path.rpartition("/")
                item = QTreeWidgetItem([region_name(name)])
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                parent = folder(parent_path)
                (parent.addChild(item) if parent else self.tree.addTopLevelItem(item))
                folders[path] = item
            return folders[path]

        for e in entries:
            parent_path = e["path"].rpartition("/")[0]
            item = QTreeWidgetItem([region_name(e["name"][:-4]), _mb(e["approx_bytes"])])
            item.setData(0, PATH, e["path"])
            item.setTextAlignment(1, Qt.AlignRight)
            parent = folder(parent_path)
            (parent.addChild(item) if parent else self.tree.addTopLevelItem(item))
            if e["path"] == chosen:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
        self.tree.sortItems(0, Qt.AscendingOrder)
        self.filter(self.search.text())

    def filter(self, text):
        hits = {e["path"] for e in maps.find(text)} if text.strip() else None

        def walk(item):
            path = item.data(0, PATH)
            if path:
                show = hits is None or path in hits
            else:
                show = any([walk(item.child(i)) for i in range(item.childCount())])
                item.setExpanded(hits is not None and show)
            item.setHidden(not show)
            return show

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def _selected(self):
        item = self.tree.currentItem()
        return item.data(0, PATH) if item else None

    def _selection(self):
        self.use_btn.setEnabled(bool(self._selected()))


class MapsPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.last_status = None

        box = QGroupBox("Your region")
        self.region = QLabel()
        self.region.setStyleSheet("font-size: 16px; font-weight: 600")
        self.server = QLabel()
        self.here = QLabel()
        self.card = QLabel()
        for w in (self.server, self.here, self.card):
            w.setWordWrap(True)
        form = forms.form()
        form.addRow("Server", self.server)
        form.addRow("This computer", self.here)
        form.addRow("Card", self.card)
        lay = QVBoxLayout(box)
        lay.addWidget(self.region)
        lay.addLayout(form)

        self.choose_btn = QPushButton("Change region\u2026")
        self.choose_btn.clicked.connect(self.choose)
        self.sync_btn = QPushButton("Sync to card")
        self.sync_btn.setDefault(True)
        self.sync_btn.clicked.connect(self.sync)
        self.check_btn = QPushButton("Check again")
        self.check_btn.clicked.connect(self.refresh_status)
        self.bar = Progress(state)
        self.bar.hide()
        self.note = QLabel()
        self.note.setWordWrap(True)
        row = QHBoxLayout()
        for b in (self.sync_btn, self.check_btn, self.choose_btn):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(self.note)
        lay = QVBoxLayout(self)
        lay.addWidget(box)

        pl = QGroupBox("Places")
        self.places = QTreeWidget()
        self.places.setHeaderLabels(["Place", "Where"])
        self.places.setRootIsDecorated(False)
        self.places.header().setStretchLastSection(True)
        self.places.setColumnWidth(0, 200)
        self.places_note = QLabel()
        self.places_note.setWordWrap(True)
        forms.muted(self.places_note)
        self.read_places_btn = QPushButton("Places to PC")
        self.read_places_btn.setToolTip("Copy the places set on the phone into this vehicle")
        self.read_places_btn.clicked.connect(self.read_places)
        self.put_places_btn = QPushButton("Places to card")
        self.put_places_btn.setToolTip("Put these places on the phone; it keeps its own and adds these "
                                       "(their Home and Work replace the phone's)")
        self.put_places_btn.clicked.connect(self.put_places)
        self.add_place_btn = QPushButton("Add place\u2026")
        self.add_place_btn.setToolTip("A place by name or address, or by its coordinates")
        self.add_place_btn.clicked.connect(self.add_place)
        self.remove_place_btn = QPushButton("Remove")
        self.remove_place_btn.setToolTip("Off this computer's list (remove it on the phone too, in Go to)")
        self.remove_place_btn.clicked.connect(self.remove_place)
        self.places.itemSelectionChanged.connect(self.places_buttons)
        pls = QVBoxLayout(pl)
        pls.addWidget(self.places, 1)
        pls.addWidget(self.places_note)
        prow = QHBoxLayout()
        prow.addWidget(self.add_place_btn)
        prow.addWidget(self.remove_place_btn)
        prow.addStretch()
        prow.addWidget(self.read_places_btn)
        prow.addWidget(self.put_places_btn)
        pls.addLayout(prow)
        lay.addWidget(pl, 1)
        credit = QLabel("Maps: Mapsforge. Place search: Geofabrik extracts. Routing: BRouter. All from OpenStreetMap"
                        " data (© OpenStreetMap contributors, ODbL).")
        forms.muted(credit)
        credit.setWordWrap(True)
        lay.addWidget(credit)

        state.target_changed.connect(self.refresh_status)
        state.target_changed.connect(self.show_places)
        state.busy_changed.connect(self._buttons)
        self.refresh_status()
        self.show_places()

    # ---- places ----

    def show_places(self):
        self.places.clear()
        ws = paths.load_config().get("workspace")
        path = places.backup_path(ws) if ws else None
        self.places_buttons()
        if not path or not os.path.exists(path):
            self.places_note.setText("Places are set on the phone (Go to on the map). Places to PC keeps a copy here.")
            return
        try:
            got = places.read(path)
        except (OSError, ValueError) as e:
            self.places_note.setText("The copy cannot be read: %s" % e)
            return
        order = {"home": 0, "work": 1, "saved": 2, "recent": 3}
        for i, p in sorted(enumerate(got), key=lambda ip: (order[ip[1]["kind"]], -ip[1].get("time", 0))):
            label = {"home": "Home", "work": "Work"}.get(p["kind"], p.get("name", ""))
            if p["kind"] == "recent":
                label += "  (recent)"
            if p["kind"] in ("home", "work") and p.get("name") not in ("Home", "Work", ""):
                label += ": " + p["name"]
            where = p.get("sub") or "%.5f, %.5f" % (p["lat"], p["lon"])
            it = QTreeWidgetItem([label, where + ("   \u2014 not on the phone yet" if p.get("waiting") else "")])
            it.setData(0, Qt.UserRole, i)
            self.places.addTopLevelItem(it)
        waiting = sum(1 for p in got if p.get("waiting"))
        self.places_note.setText("%d added here, not on the phone yet." % waiting if waiting else
                                 "The phone keeps its own places and adds these.")

    def places_buttons(self):
        ws = paths.load_config().get("workspace")
        path = places.backup_path(ws) if ws else None
        ok = bool(ws) and self.state.has_target() and not self.state.busy
        self.read_places_btn.setEnabled(ok)
        self.put_places_btn.setEnabled(ok and bool(path) and os.path.exists(path))
        self.add_place_btn.setEnabled(bool(ws))
        self.remove_place_btn.setEnabled(bool(ws) and bool(self.places.selectedItems()))

    def _places_job(self, what, fn, done):
        if not self.state.begin(what):
            return
        self.places_note.setText(what[0].upper() + what[1:] + "\u2026")
        self.state.watch(self.places_note)

        def ok(r):
            self.state.end()
            done(r)

        def failed(msg):
            self.state.end()
            self.show_places()
            forms.error(self, "Places", msg)
        worker.run(fn, ok, failed)

    def _target(self):
        """The phone or card, or None after saying why it could not be reached."""
        try:
            return self.state.target()
        except SystemExit as e:
            self._error(str(e.code))
            return None

    def read_places(self):
        ws, target = paths.load_config().get("workspace"), self._target()
        if target is None:
            return
        self._places_job("copying places from the phone", lambda: places.backup(target, ws), lambda r: self.show_places())

    def add_place(self):
        ws = paths.load_config().get("workspace")
        near = None
        try:
            home = [p for p in places.read(places.backup_path(ws)) if p["kind"] == "home"]
            near = (home[0]["lat"], home[0]["lon"]) if home else None
        except (OSError, ValueError):
            pass
        d = PlaceDialog(self, near)
        if d.exec() == PlaceDialog.Accepted and d.result:
            kind, name, lat, lon, sub = d.result
            try:
                places.add(ws, kind, name, lat, lon, sub)
            except (OSError, ValueError) as e:
                forms.error(self, "Add place", str(e))
            self.show_places()

    def remove_place(self):
        items = self.places.selectedItems()
        if not items:
            return
        ws = paths.load_config().get("workspace")
        i = items[0].data(0, Qt.UserRole)
        p = places.read(places.backup_path(ws))[i]
        if not p.get("waiting") and QMessageBox.question(
                self, "Remove place", "Take %s off this computer's list? The phone keeps it until you remove it there "
                "(Go to on the map), and the next Places to PC brings it back." % (p.get("name") or p["kind"])) != QMessageBox.Yes:
            return
        places.remove(ws, i)
        self.show_places()

    def put_places(self):
        ws, target = paths.load_config().get("workspace"), self._target()
        if target is None:
            return

        def done(r):
            self.places_note.setText("On the card. " + ("The app " + r["app"] + "." if r["app"] else
                                                        "The app adds them when it next starts."))
        self._places_job("putting places on the card", lambda: places.restore(target, ws), done)

    # ---- the chosen region ----

    def choose(self):
        if self.state.busy:
            return
        d = RegionDialog(self)
        if d.exec() != QDialog.Accepted or not d.path or d.path == maps.chosen():
            return
        path = d.path

        def done(_):
            self.refresh_status()
            self.note.setText("Now press Sync to card to put %s on the phone." % region_name(os.path.basename(path)[:-4]))
        worker.run(lambda: maps.choose(path), done, self._error)

    def refresh_status(self):
        region = maps.chosen()
        self.region.setText(region_name(os.path.basename(region)[:-4]) if region else "None chosen")
        self.server.setText("checking…" if region else "")
        self.here.setText("")
        self.card.setText("")
        self._buttons()
        if not region:
            self.note.setText("Press Change region… to pick the map for this vehicle.")
            return

        def work():
            try:
                target = self.state.target()
            except SystemExit:
                target = None
            return maps.status(target, layout.MAPS_DIR), target is not None
        worker.run(work, self._status, self._error)

    def _status(self, result):
        st, have_target = result
        self.last_status = st
        srv = st["server"]
        self.server.setText("%s, built %s" % (_mb(srv["bytes"]), _day(srv["modified"])) if srv
                            else "not reachable (%s)" % st.get("server_error", ""))
        c = st["cache"]
        if c:
            self.here.setText("%s, built %s%s" % (_mb(c["bytes"]), _day(c["written"]),
                                                  " — a newer build is on the server" if c["outdated"] else ""))
        else:
            self.here.setText("not downloaded yet")
        if not have_target:
            self.card.setText("Choose a phone or card on the Phone page")
        else:
            card = st["card"]
            text = ("not there" if not card else "up to date" if card["current"] and not (c and c["outdated"])
                    else "an older build")
            if st["card_other"]:
                text += "; also on the card: " + ", ".join(st["card_other"]) + " (Sync replaces it)"
            self.card.setText("%s (%s)" % (text[0].upper() + text[1:], self.state.label()))

    def _buttons(self):
        has_target = self.state.has_target()
        busy = bool(self.state.busy)
        self.sync_btn.setEnabled(bool(maps.chosen()) and has_target and not busy)
        self.sync_btn.setToolTip("Wait for %s to finish" % self.state.busy if busy else
                                 "" if has_target else "Choose a phone or card on the Phone page first")
        self.check_btn.setEnabled(not busy)
        self.places_buttons()
        self.choose_btn.setEnabled(not busy)

    # ---- sync ----

    def sync(self):
        try:
            target = self.state.target()
        except SystemExit as e:
            self._error(str(e.code))
            return
        st = self.last_status or {}
        ask = []
        if not st.get("cache") or st["cache"].get("outdated"):
            srv = st.get("server") or {}
            ask.append("First it downloads the map (%s) to this computer." % (_mb(srv.get("bytes")) or "several hundred MB"))
        if st.get("card_other"):
            ask.append("It removes %s from the card: the app shows one map." % ", ".join(st["card_other"]))
        size = (st.get("cache") or st.get("server") or {}).get("bytes", 0)
        if size and not (st.get("card") or {}).get("current"):
            rate = 1.3e6 if ":" in (self.state.serial or "") else 8e6
            ask.append("Copying it to %s takes about %d minutes." % (self.state.label(), max(1, round(size / rate / 60))))
        if ask and QMessageBox.question(self, "Sync to card", " ".join(ask) + " Go ahead?") != QMessageBox.Yes:
            return
        if not self.state.begin("syncing the map"):
            return
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.show()
        self.note.setText("Checking the map…")
        self.state.watch(self.note)

        def work(report):
            # report(None, None) switches the bar to "copying", which has no progress to show
            msg = maps.sync(target, layout.MAPS_DIR, report, copying=lambda: report(None, None))
            note = maps.tell_app(target, msg)
            # the routing tiles for offline navigation come from the same region
            report("routing", None)
            r = routing.sync(target, lambda i, n, d, t, name: report(("tiles", i, n, d, t), None),
                             copying=lambda: report(None, None))
            # and the place search, built here from the region's OpenStreetMap data
            report("search", None)
            s = search.sync(target, lambda d, t: report(("search", d, t), None), copying=lambda: report(None, None),
                            log=lambda line: report(("log", line), None))
            reply = target.notify_synced(["search"]) if s["copied"] else None
            return ["Map: " + msg + (" (" + note + ")" if note else ""),
                    "Routing: %d tiles, %d copied" % (r["tiles"], r["copied"]),
                    "Place search: %s, %s" % (_mb(s["bytes"]), "copied" if s["copied"] else "already there")
                    + (" (the app " + reply + ")" if reply else "")]

        worker.run(work, self._synced, self._sync_failed, progress=self._progress)

    def _progress(self, done, total):
        if done == "routing":
            self.note.setText("checking the routing tiles for offline navigation…")
            return
        if done == "search":
            self.note.setText("checking the place search…")
            return
        if isinstance(done, tuple) and done[0] == "search":
            _, d, t = done
            self.bar.setRange(0, 100)
            self.bar.setValue(int(d * 100 / t) if t else 100)
            self.note.setText("downloading OpenStreetMap data for the place search… %s of %s" % (_mb(d), _mb(t)))
            return
        if isinstance(done, tuple) and done[0] == "log":
            self.bar.setRange(0, 0)
            self.note.setText(done[1][0].upper() + done[1][1:])
            return
        if isinstance(done, tuple):
            _, i, n, d, t = done
            self.bar.setRange(0, 100)
            self.bar.setValue(int(d * 100 / t) if t else 100)
            self.note.setText("downloading routing tile %d of %d… %s of %s" % (i, n, _mb(d), _mb(t)))
            return
        if done is None:
            self.bar.setRange(0, 0)
            self.note.setText("Copying to %s…" % self.state.label())
        elif total:
            self.bar.setValue(int(done * 100 / total))
            self.note.setText("downloading… %s of %s" % (_mb(done), _mb(total)))

    def _synced(self, lines):
        self.state.end()
        self.bar.hide()
        self.refresh_status()
        self.note.setText("The card is up to date.\n" + "\n".join("\u2022 " + l for l in lines))

    def _sync_failed(self, msg):
        self.state.end()
        self.bar.hide()
        self.note.setText("")
        self._buttons()
        forms.error(self, "Sync to card", msg)

    def _error(self, msg):
        forms.error(self, "", msg)
