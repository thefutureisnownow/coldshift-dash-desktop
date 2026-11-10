"""What the pages share: the open vehicle's phone or card (remembered with the vehicle), the names of
the phones adb lists, and the one job that may be talking to the phone at a time."""
import os

from PySide6.QtCore import QObject, Signal

from .. import paths
from ..transport import AdbTarget, FolderTarget


class State(QObject):
    target_changed = Signal()
    busy_changed = Signal()
    names_changed = Signal()        # phone model names learned (labels can say "G7-L01")
    progress_changed = Signal()     # how far the running job is (span, value)

    def __init__(self):
        super().__init__()
        cfg = paths.load_config()
        self.serial = cfg.get("phone")
        self.card = cfg.get("card")
        self.models = {}            # serial -> model name, from the Phone page's list
        self.online = None          # serials adb listed as ready, from the same list (None: not listed yet)
        self.busy = None            # what is running ("syncing music"), or None
        self.note = None            # the page's label saying what the running job is doing (see watch)
        self.span = (0, 0)          # the running job's progress, as a progress bar's range: (0, 0) is "busy"
        self.value = 0
        self.steps = []             # for a job of several parts: their names, in order
        self.step = 0               # the part running now
        self.detail = ""            # what that part is doing ("Downloading: 216 MB of 560 MB")

    def _save(self):
        cfg = paths.load_config()
        cfg["phone"], cfg["card"] = self.serial, self.card
        paths.save_config({k: v for k, v in cfg.items() if v is not None})

    def use_phone(self, serial):
        self.serial, self.card = serial, None
        self._save()
        self.target_changed.emit()

    def use_card(self, folder):
        self.serial, self.card = None, folder
        self._save()
        self.target_changed.emit()

    def has_target(self):
        return bool(self.serial or self.card)

    def label(self):
        """The phone or card in words: "G7-L01 over USB", "the card in NO NAME"."""
        if self.serial:
            name = self.models.get(self.serial, "").replace("_", "-") or "phone " + self.serial
            return name + (" over Wi-Fi" if ":" in self.serial else " over USB")
        if self.card:
            return "the card in " + (os.path.basename(self.card.rstrip(os.sep)) or self.card)
        return "no phone or card chosen"

    def connected(self):
        """Whether the chosen phone was ready when adb last listed the phones (None: not listed yet), or
        the chosen card's folder is there."""
        if self.serial:
            return None if self.online is None else self.serial in self.online
        return bool(self.card) and os.path.isdir(self.card)

    # ---- one job at a time ----

    def begin(self, what):
        """Claims the phone for a job; False (and nothing changes) if another job has it."""
        if self.busy:
            return False
        self.busy = what
        self.span, self.value = (0, 0), 0
        self.steps, self.step, self.detail = [], 0, ""
        self.busy_changed.emit()
        return True

    QUIET = ("checking", "looking")     # jobs that only read: quick, and nothing to keep the user out of

    def quiet(self):
        return bool(self.busy) and self.busy.startswith(self.QUIET)

    def watch(self, note):
        """Called by a page after begin(): the label where it says what its job is doing, which the
        window's sync dialog repeats."""
        self.note = note

    def set_progress(self, span=None, value=None, detail=None):
        if span is not None:
            self.span = span
        if value is not None:
            self.value = value
        if detail is not None:
            self.detail = detail
        self.progress_changed.emit()

    def set_steps(self, names):
        self.steps, self.step, self.detail = list(names), 0, ""
        self.progress_changed.emit()

    def set_step(self, i, detail=""):
        self.step, self.detail, self.span, self.value = i, detail, (0, 0), 0
        self.progress_changed.emit()

    def end(self):
        self.note = None
        self.span, self.value = (0, 0), 0
        self.steps, self.step, self.detail = [], 0, ""
        self.busy = None
        self.busy_changed.emit()

    def sources(self):
        """Everywhere the app may have written recordings: the card, and on a phone also internal
        storage (the app falls back to it when there is no card)."""
        t = self.target()
        if t.kind == "adb" and t.card != "/storage/emulated/0":
            return [t, AdbTarget(t.serial, t.adb, "/storage/emulated/0")]
        return [t]

    def target(self):
        """A transport for the chosen phone or card. Only ever the one the user picked."""
        if self.serial:
            return AdbTarget(self.serial)
        if self.card:
            return FolderTarget(self.card)
        raise SystemExit("Choose a phone or a card on the Phone page first.")


class Progress:
    """What a page tells how far its job is: used like a progress bar (setRange, setValue, show, hide),
    but the page has no bar. The window shows the one there is: in the sync dialog, or for a look at the
    phone in the strip under the page."""
    def __init__(self, state):
        self.state = state
        self.on = False

    def setRange(self, low, high):
        self.state.set_progress(span=(low, high))

    def setValue(self, value):
        self.state.set_progress(value=value)

    def show(self):
        self.on = True

    def hide(self):
        self.on = False

    def setVisible(self, on):
        self.on = bool(on)

    def isVisible(self):
        return self.on
