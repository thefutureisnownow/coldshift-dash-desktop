"""Overview: where each part of the vehicle stands against its phone, and one Sync for all of it.

A card per part (map, music, voices, look, recordings, and what the phone records). The page compares
each with the phone when it is shown, one after the other in a single job, and tells the window, which
puts the same light beside the part's page in the sidebar. Sync copies what the phone recorded to this
computer, then puts the whole vehicle on the phone; only what is missing or different is copied.

Copy from phone goes the other way: the phone's look, voices, map and music replace this computer's
(fromphone), then what the phone recorded comes too. Nothing is put on the phone."""
import os
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from .. import backup, fromphone, layout, logbook, maps, mirror, paths, places, profile, recordings, track, voice
from . import forms, theme, worker
from .state import Progress
from .maps_page import region_name
from .recordings_page import recordings_dest

# what a card's light means
GOOD, TODO, IDLE, BAD = "good", "todo", "idle", "bad"
COLOURS = {GOOD: theme.GOOD, TODO: theme.WAIT, IDLE: theme.OFF, BAD: forms.WARN}

# key, title, the page a click opens
AREAS = (("map", "Map", "Maps"), ("music", "Music", "Music"), ("voices", "Voices", "Voices"),
         ("look", "Look", "Look"), ("recordings", "Recordings", "Recordings"),
         ("phone", "Log book, track and places", "Log book"))


def _size(n):
    return "%.1f GB" % (n / 1e9) if n >= 1e9 else "%.0f MB" % (n / 1e6)


# the sync's steps as the dialog lists them, and what each is doing before it reports any progress
STEP_NAMES = {"from the phone": "Places, settings, log book and track from the phone",
              "recordings": "Recordings to this computer", "places and settings": "Places and settings to the phone",
              "log book and track": "Log book and track to the phone", "look": "Look", "voices": "Voices",
              "map": "Map", "routing": "Routing for navigation", "place search": "Place search", "music": "Music",
              "look from the phone": "Look from the phone", "voices from the phone": "Voice packs from the phone",
              "map from the phone": "Map from the phone", "music from the phone": "Music from the phone"}
STEP_STARTS = {"from the phone": "Reading the phone…", "recordings": "Looking for new recordings…",
               "map from the phone": "Copying the map to this computer…",
               "music from the phone": "Comparing the phone's music with this computer's…",
               "map": "Checking the server for a newer map…", "routing": "Checking the routing tiles…",
               "place search": "Checking the place search…", "music": "Comparing the music with the phone…"}
DOWNLOADS = ("map", "routing", "place search")       # steps whose progress is a download, in bytes


def _doing(step, done, total, moved, seconds):
    """What the running step is doing, from its progress: amounts, and for a download its speed and the
    time left (`moved` bytes in `seconds` since this step's progress began)."""
    if step == "music":
        return "Copying file %d of %d" % (done, total)
    if step in DOWNLOADS:           # counted as the Maps page counts a map's size
        text = "Downloading: %.0f MB of %.0f MB" % (done / 1048576, total / 1048576)
    else:
        text = "Copying: %s of %s" % (_size(done), _size(total))
    if step in DOWNLOADS and seconds >= 3 and moved > 0:
        rate = moved / seconds
        left = (total - done) / rate
        text += " · %.1f MB/s · %s left" % (rate / 1048576, "about %d min" % round(left / 60) if left >= 90 else "under a minute"
                                            if left < 45 else "about a minute")
    return text


def _count(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else many or one + "s")


def _and(items):
    """["a", "b", "c"] -> "a, b and c"."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def songs(vehicle):
    """(songs, bytes) in the vehicle's music folder."""
    n = size = 0
    d = os.path.join(vehicle, *layout.MUSIC_DIR.split("/"))
    for root, _, files in os.walk(d) if os.path.isdir(d) else ():
        for f in files:
            if f.lower().endswith(layout.AUDIO_EXT) and not f.startswith("."):
                n += 1
                size += os.path.getsize(os.path.join(root, f))
    return n, size


def local(vehicle):
    """What this computer holds of each part, in a few words (no phone needed)."""
    out = {}
    region = maps.chosen()
    out["map"] = region_name(os.path.basename(region)[:-4]) if region else "No region chosen"
    n, size = songs(vehicle)
    out["music"] = "%s, %s" % (_count(n, "song"), _size(size)) if n else "No music yet"
    own = len(voice.packs(vehicle))
    out["voices"] = "Angie and %s of your own" % own if own else "Angie, the built-in voice"
    out["look"] = profile.load(vehicle).get("title") or "The built-in look"
    dest = recordings_dest()
    out["recordings"] = "Copies kept on this computer" if dest else "No folder for copies yet"
    out["phone"] = "%s, %s" % (_count(len(logbook.entries(vehicle)), "log book entry", "log book entries"),
                               _count(len(track.segments(vehicle)), "track segment"))
    return out


def compare(target, sources, vehicle, report):
    """Compares each part with the phone, calling report(key, (light, sentence, moves)) as each is known.
    `moves` is what a sync would do that is worth asking about first: {"download", "to_phone", "to_pc"} in
    bytes and "says", sentences for the question."""
    def part(key, fn):
        try:
            r = fn()
            report(key, r if len(r) == 3 else r + ({},))
        except SystemExit as e:
            report(key, (BAD, str(e.code), {}))
        except Exception as e:
            report(key, (BAD, str(e) or e.__class__.__name__, {}))

    def the_map():
        st = maps.status(target, layout.MAPS_DIR)
        if not st["region"]:
            return IDLE, "Choose a region on the Maps page."
        cache, srv = st["cache"], st["server"] or {}
        fetch = not cache or cache["outdated"]
        current = bool(st["card"]) and st["card"]["current"] and not fetch
        size = srv.get("bytes") or (cache or {}).get("bytes") or 0
        moves = {"download": size if fetch else 0, "to_phone": 0 if current else size, "says": []}
        name = region_name(os.path.basename(st["region"])[:-4])
        if fetch:
            moves["says"].append("Download the %s map (%s)." % (name, "%.0f MB" % (size / 1024 / 1024) if size else "several hundred MB"))
        if not current:
            moves["says"].append("Copy the map to the phone.")
        if st["card_other"]:
            moves["says"].append("Remove %s from the phone: the app shows one map." % ", ".join(st["card_other"]))
            moves["removes"] = True
        if st["card"] is None:
            return TODO, "Not on the phone yet.", moves
        if cache and cache["outdated"]:
            return TODO, "A newer build is on the server.", moves
        if not current:
            return TODO, "The phone has a different build.", moves
        return GOOD, "On the phone, up to date.", moves if st["card_other"] else {}

    def music():
        if not songs(vehicle)[0]:
            return IDLE, "Add music on the Music page."
        r = mirror.push_music(target, vehicle, dry_run=True)
        copy = r["music"]["copy"]
        if copy:
            size = sum(c[2] for c in copy)
            return (TODO, "%s to copy (%s)." % (_count(len(copy), "song"), _size(size)),
                    {"to_phone": size, "says": ["Copy %s to the phone (%s)." % (_count(len(copy), "song"), _size(size))]})
        return GOOD, "All on the phone."

    def voices():
        r = voice.sync(target, vehicle, dry_run=True)
        n = r["copied"] + r["removed"]
        return (TODO, "%s not on the phone yet." % _count(n, "change")) if n else (GOOD, "On the phone, up to date.")

    def look():
        n = profile.sync(target, vehicle, dry_run=True)["files"]
        return (TODO, "%s not on the phone yet." % _count(n, "change")) if n else (GOOD, "On the phone, up to date.")

    def recs():
        dest = recordings_dest()
        if not dest:
            return IDLE, "Choose where copies go on the Recordings page."
        items = recordings.status(sources, dest)["items"]
        new = [i for i in items if not i["pulled"] and not i["pulled_before"] and not i["busy"]]
        if new:
            size = sum(i["size"] for i in new)
            return (TODO, "%s not on this computer yet (%s)." % (_count(len(new), "file"), _size(size)),
                    {"to_pc": size, "says": ["Copy %s to this computer (%s)." % (_count(len(new), "recording file"), _size(size))]})
        return GOOD, "All copied to this computer." if items else "Nothing recorded on the phone yet."

    for key, fn in (("look", look), ("voices", voices), ("map", the_map), ("music", music), ("recordings", recs)):
        part(key, fn)


class Card(QFrame):
    """One part of the vehicle: a light, its name, what this computer holds and how the phone compares.
    A click opens the part's page."""
    clicked = Signal()

    def __init__(self, title):
        super().__init__()
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.light = QLabel()
        self.light.setFixedSize(10, 10)
        name = forms.muted(QLabel(title))
        self.value = QLabel()
        self.value.setObjectName("cardvalue")
        self.value.setWordWrap(True)
        self.detail = forms.note("")
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(self.light)
        head.addWidget(name, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)
        lay.addLayout(head)
        lay.addWidget(self.value)
        lay.addWidget(self.detail)
        lay.addStretch()
        self.show_state(IDLE, "")

    def show_state(self, light, text):
        self.light.setStyleSheet("background: %s; border-radius: 5px" % COLOURS[light])
        self.detail.setText(text)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


class OverviewPage(QWidget):
    open_page = Signal(str)             # a card was clicked: the page's name
    area_changed = Signal(str, str)     # a page's name and its light's colour ("" for none)

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.mine = False               # this page has the phone (a check or a sync)
        self.fresh = False              # the cards show the phone as it is now
        self.lights = {}
        self.moves = {}                 # per part, what a sync would move (see compare)

        self.headline = QLabel()
        self.headline.setObjectName("headline")
        self.note = forms.note("")
        self.sync_btn = QPushButton("Sync now")
        self.sync_btn.setDefault(True)
        self.sync_btn.setToolTip("Copy what the phone recorded to this computer, then put everything the phone lacks on it")
        self.sync_btn.clicked.connect(self.sync)
        self.pull_btn = QPushButton("Copy from phone")
        self.pull_btn.setToolTip("Replace this computer's look, voice packs, map and music with the phone's, and copy "
                                 "its places, log book and recordings. Nothing on the phone changes.")
        self.pull_btn.clicked.connect(self.copy_from_phone)
        self.check_btn = QPushButton("Check again")
        self.check_btn.clicked.connect(self.check)
        self.bar = Progress(state)
        self.bar.hide()
        words = QVBoxLayout()
        words.setSpacing(4)
        words.addWidget(self.headline)
        words.addWidget(self.note)
        top = QHBoxLayout()
        top.addLayout(words, 1)
        top.addWidget(self.check_btn, 0, Qt.AlignTop)
        top.addWidget(self.pull_btn, 0, Qt.AlignTop)
        top.addWidget(self.sync_btn, 0, Qt.AlignTop)
        hero = QFrame()
        hero.setObjectName("hero")
        h = QVBoxLayout(hero)
        h.setContentsMargins(20, 18, 20, 18)
        h.setSpacing(12)
        h.addLayout(top)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.cards = {}
        for i, (key, title, page) in enumerate(AREAS):
            card = Card(title)
            card.clicked.connect(lambda page=page: self.open_page.emit(page))
            self.cards[key] = card
            grid.addWidget(card, i // 3, i % 3)
        for c in range(3):
            grid.setColumnStretch(c, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(hero)
        lay.addLayout(grid)
        lay.addStretch()

        # after another page's job the phone may differ from the cards: look again once it is quiet
        self.later = QTimer(self)
        self.later.setSingleShot(True)
        self.later.setInterval(1500)
        self.later.timeout.connect(self._look_again)
        self.was_busy = None
        state.target_changed.connect(self._target_changed)
        state.names_changed.connect(self._maybe_check)
        state.busy_changed.connect(self._busy_changed)
        self.show_local()
        self._buttons()

    def vehicle(self):
        return paths.load_config().get("workspace")

    # ---- what is shown ----

    def show_local(self):
        v = self.vehicle()
        if not v:
            return
        try:
            for key, text in local(v).items():
                self.cards[key].value.setText(text)
        except (OSError, ValueError) as e:
            self.note.setText("This vehicle's folder cannot be read: %s." % e)

    def show_phone_copy(self):
        """The card for what only the phone records: what has been copied from it so far."""
        try:
            b = backup.saved(self.vehicle())
        except (OSError, ValueError) as e:
            self._set("phone", BAD, "The copy from the phone cannot be read: %s." % e)
            return
        parts = []
        if b["places"] is not None:
            parts.append("places (%s)" % places.describe(b["places"]))
        if b["settings"] is not None:
            parts.append("the app's settings")
        self._set("phone", IDLE, "Copied from the phone on every sync. So far also: " + " and ".join(parts) + "."
                  if parts else "Copied from the phone on every sync.")

    def _set(self, key, light, text):
        self.lights[key] = light
        self.cards[key].show_state(light, text)
        page = [p for k, _, p in AREAS if k == key][0]
        if key != "phone":
            self.area_changed.emit(page, COLOURS[light] if light != IDLE else "")

    def _unknown(self, text=""):
        for key, _, _ in AREAS:
            if key != "phone":
                self._set(key, IDLE, text)
        self.fresh = False

    def _headline(self):
        s = self.state
        if not s.has_target():
            self.headline.setText("No phone or card chosen")
            self.note.setText("Choose this vehicle's phone, or its card in a reader, on the Phone page.")
        elif s.connected() is False:
            self.headline.setText("%s is not connected" % (s.label()[0].upper() + s.label()[1:]))
            self.note.setText("Plug it in (or check its Wi-Fi), then press Check again.")
        elif not self.fresh:
            self.headline.setText("Not compared with the phone yet")
        else:
            todo = sum(1 for v in self.lights.values() if v == TODO)
            bad = sum(1 for v in self.lights.values() if v == BAD)
            self.headline.setText("%s to sync" % _count(todo, "thing") if todo else
                                  "Some parts could not be checked" if bad else "Everything is up to date")
            self.note.setText("Compared with %s." % s.label())

    def _buttons(self):
        ok = bool(self.vehicle()) and self.state.has_target() and not self.state.busy
        self.sync_btn.setEnabled(ok)
        self.check_btn.setEnabled(ok)
        self.pull_btn.setEnabled(ok)
        tip = "Wait for %s to finish" % self.state.busy if self.state.busy else ""
        self.check_btn.setToolTip(tip)

    # ---- when to look ----

    def showEvent(self, e):
        super().showEvent(e)
        self.show_local()
        self.show_phone_copy()
        self._maybe_check()

    def _target_changed(self):
        self._unknown()
        self._headline()
        self._buttons()
        self._maybe_check()

    def _maybe_check(self):
        if self.isVisible() and not self.fresh and not self.state.busy and self.state.connected():
            self.check()
        elif not self.mine:
            self._headline()

    def _busy_changed(self):
        self._buttons()
        busy = self.state.busy
        if busy is None and self.was_busy and not self.mine:
            # a page's own look at the phone ("checking…", "looking…") changes nothing; anything else may have
            if not self.was_busy.startswith(("checking", "looking")):
                self.fresh = False
                self.later.start()
        self.was_busy = busy

    def _look_again(self):
        if not self.state.busy and self.state.has_target() and self.state.connected():
            self.check()

    # ---- check ----

    def _begin(self, what, text):
        if not self.state.begin(what):
            return False
        self.mine = True
        self.headline.setText(text)
        self.bar.setRange(0, 0)
        self.bar.show()
        self.state.watch(self.note)
        return True

    def _end(self):
        self.bar.hide()
        self.state.end()                # while still "mine": our own job ending is not another page's
        self.mine = False

    def check(self, after=""):
        v = self.vehicle()
        if not v or not self.state.has_target() or self.state.busy:
            return
        try:
            target, sources = self.state.target(), self.state.sources()
        except SystemExit as e:
            self.note.setText(str(e.code))
            return
        if not self._begin("checking the phone", "Comparing with %s…" % self.state.label()):
            return
        self.note.setText(after)
        for key, _, _ in AREAS:
            if key != "phone":
                self.cards[key].show_state(IDLE, "Checking…")

        self.moves = {}

        def progress(key, result):
            light, text, moves = result
            self.moves[key] = moves
            self._set(key, light, text)

        def done(_):
            self.fresh = True
            self._end()
            self._headline()
            if after:
                self.note.setText(after)

        def failed(msg):
            self._end()
            self._unknown()
            self.headline.setText("The phone could not be checked")
            self.note.setText(msg)
        worker.run(lambda report: compare(target, sources, v, report), done, failed, progress=progress)

    # ---- sync ----

    ASK_ABOVE = 100e6       # bytes: a sync that moves less, downloads nothing and removes nothing just runs

    def _question(self):
        """What to ask before a sync, or None when it is small enough to just run."""
        label = self.state.label()
        if not self.fresh:
            return ("This vehicle has not been compared with %s yet, so the sync may copy a lot: the map, the "
                    "music and the recordings. A new phone can take an hour or more over USB.\n\nSync now?" % label)
        moves = [m for m in self.moves.values() if m]
        total = sum(m.get("to_phone", 0) + m.get("to_pc", 0) for m in moves)
        says = [line for key, _, _ in AREAS for line in self.moves.get(key, {}).get("says", [])]
        removes = any(m.get("removes") for m in moves)
        if not says or (total < self.ASK_ABOVE and not removes and not any(m.get("download") for m in moves)):
            return None
        rate = 1.3e6 if ":" in (self.state.serial or "") else 8e6        # measured: Wi-Fi and USB, bytes a second
        minutes = max(1, round(total / rate / 60))
        return ("Syncing with %s will:\n\n%s\n\nCopying takes about %s%s. Nothing else is removed or replaced."
                "\n\nSync now?" % (label, "\n".join("\u2022 " + line for line in says), _count(minutes, "minute"),
                                    ", after the download" if any(m.get("download") for m in moves) else ""))

    def sync(self):
        if self.state.busy:
            return
        ask = self._question()
        if ask and QMessageBox.question(self, "Sync", ask) != QMessageBox.Yes:
            return
        self._run(pull_first=False, push=True)

    def copy_from_phone(self):
        if self.state.busy:
            return
        label = self.state.label()
        text = ("Replace this computer's copy of the vehicle with what %s holds: its look, voice packs, map and music "
                "take the place of this computer's, and its places, settings, log book%s come too.\n\n"
                "Files this computer has that the phone does not are moved into folders ending .previous in the "
                "vehicle's folder, not deleted. Nothing on the phone changes.\n\nCopy from the phone now?"
                % (label, ", track and recordings" if recordings_dest() else " and track"))
        if QMessageBox.question(self, "Copy from phone", text) != QMessageBox.Yes:
            return
        self._run(pull_first=True, push=False)

    def _run(self, pull_first, push):
        """The sync's job: with pull_first the phone's look, voices, map and music come here first
        (fromphone.pull); then what the phone recorded; then, with push, the whole vehicle goes on the phone."""
        v = self.vehicle()
        try:
            target, sources = self.state.target(), self.state.sources()
        except SystemExit as e:
            forms.error(self, "Sync", str(e.code))
            return
        what, text = (("syncing everything", "Syncing with %s…") if push else
                      ("copying from the phone", "Copying from %s…"))
        if not self._begin(what, text % self.state.label()):
            return
        dest = recordings_dest()
        steps = ((list(fromphone.STEPS) if pull_first else []) + ["from the phone"] + (["recordings"] if dest else [])
                 + (list(backup.STEPS) if push else []))
        self.step = steps[0]
        self.state.set_steps([STEP_NAMES.get(s, s) for s in steps])
        began = [time.time(), None]         # when the running step's progress began, and at how much

        def work(report):
            out = {}
            if pull_first:
                out["pulled"] = fromphone.pull(target, v, step=lambda name: report("step", name),
                                               progress=lambda d, t: report(d, t))
            report("step", "from the phone")
            out["from"] = backup.backup(target, v)
            if dest:
                report("step", "recordings")
                out["recordings"] = recordings.pull(sources, dest, log=lambda m: None,
                                                    progress=lambda i, n, d, t, key: report(d, t))
            if push:
                out["to"] = backup.restore(target, v, step=lambda name: report("step", name),
                                           progress=lambda d, t: report(d, t), copying=lambda: report("copying", None))
            return out

        def progress(a, b):
            if a == "step":
                self.step = b
                i = steps.index(b) if b in steps else 0
                self.note.setText("Step %d of %d: %s…" % (i + 1, len(steps), b))
                began[:] = [time.time(), None]
                self.state.set_step(i, STEP_STARTS.get(b, ""))
            elif a == "copying":
                self.state.set_progress(span=(0, 0), detail="Copying to %s…" % self.state.label())
            elif b:
                if began[1] is None:
                    began[:] = [time.time(), a]
                self.state.set_progress(span=(0, 1000), value=int(a * 1000 / b),
                                        detail=_doing(self.step, a, b, a - began[1], time.time() - began[0]))

        def done(r):
            self._end()
            said = []
            pulled = fromphone.says(r["pulled"]) if r.get("pulled") else []
            if pulled:
                said.append("Copied from the phone: %s." % _and(pulled))
            mp = (r.get("pulled") or {}).get("map") or {}
            if mp.get("name") and mp.get("found") is not True:
                said.append("Choose the region for %s on the Maps page%s." % (
                    mp["name"], " (the server could not be asked)" if mp.get("found") is None else ""))
            moved = fromphone.moved(r["pulled"]) if r.get("pulled") else []
            if moved:
                said.append("What this computer had instead is in %s in the vehicle's folder." % _and(moved))
            if r["from"]["changed"]:
                said.append(("Also copied: %s." if pulled else "Copied from the phone: %s.") % ", ".join(r["from"]["changed"]))
            rec = r.get("recordings")
            if rec and rec["pulled"]:
                said.append("%s copied (%s)." % (_count(rec["pulled"], "recording file"), _size(rec["bytes"])))
            if rec and rec["skipped_busy"]:
                said.append("%s still being recorded, left for next time." % _count(rec["skipped_busy"], "file"))
            if r.get("to", {}).get("app"):
                said.append("The app %s." % r["to"]["app"].replace(",", ", "))
            self.show_local()
            self.show_phone_copy()
            self._buttons()
            self.check(after=(("Synced. " if push else "") + " ".join(said)).strip() or "Nothing new on the phone.")

        def failed(msg):
            self._end()
            self._unknown()
            said = ("Cancelled at: %s." if msg == worker.CANCELLED else
                    ("The sync stopped at: %s." if push else "The copy stopped at: %s.")) % self.step
            said += " What was copied before that stays."
            self.headline.setText("Cancelled" if msg == worker.CANCELLED else "The sync stopped" if push else "The copy stopped")
            self.note.setText(said)
            forms.error(self, "Sync" if push else "Copy from phone", msg)
            self.check(after=said)          # the cards as they are now
        worker.run(work, done, failed, progress=progress)
