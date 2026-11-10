"""python -m dashsync.gui"""
import os
import sys
import time

import shiboken6
from PySide6.QtCore import QSettings, QSize, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import VERSION, paths, profile, vehicles
from . import forms, theme
from .busy_dialog import BusyDialog
from .look_page import LookPage
from .maps_page import MapsPage
from .music_page import MusicPage
from .overview_page import OverviewPage
from .phone_page import PhonePage
from .recordings_page import RecordingsPage
from .state import State
from .track_page import TrackPage
from .logbook_page import LogbookPage
from .connect_dialog import ConnectDialog
from .convoy_page import ConvoyPage
from .vehicle_picker import VehiclePicker, car_icon
from .voices_page import VoicesPage

BRAND = paths.app_assets("brand")


WEBSITE = "https://coldshift.racing"


def brand(name):
    p = os.path.join(BRAND, name)
    return p if os.path.exists(p) else None


def app_icon():
    """The app's icon as a picture (the dash logo on its tile): packaged beside the brand pictures, else
    from packaging/icons in the repository; the bare logo if neither is there."""
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(BRAND, "icon-512.png"),
              os.path.normpath(os.path.join(here, "..", "..", "packaging", "icons", "icon-512.png"))):
        if os.path.exists(p):
            return p
    return brand("dash-logo-512.png")


def keep_log():
    """The packaged app has no terminal: what it would print there (errors from background jobs, crashes)
    goes to a file instead, started afresh once it is large."""
    path = paths.log_file()
    try:
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".old")
        out = open(path, "a", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        return
    out.write("\n== coldshift.dash %s, %s, %s\n" % (VERSION, sys.platform, time.strftime("%Y-%m-%d %H:%M:%S")))
    sys.stdout = sys.stderr = out


def dot(colour, size=10):
    """A round status light for the phone chip."""
    pix = QPixmap(size * 2, size * 2)
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(colour))
    p.drawEllipse(0, 0, size, size)
    p.end()
    return QIcon(pix)


class About(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("About coldshift.dash")
        lay = QVBoxLayout(self)
        # the logo on its tile: bare, its black edge is lost on this dark window
        for path, size in ((app_icon(), 128), (brand("tfinn-logo.png"), 96)):
            if path:
                pic = QLabel()
                pix = QPixmap(path).scaled(size * 2, size * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pix.setDevicePixelRatio(2)
                pic.setPixmap(pix)
                pic.setAlignment(Qt.AlignCenter)
                lay.addWidget(pic)
        for text, style in (("coldshift.dash", "font-size: 18px; font-weight: 600"), ("Version " + VERSION, ""),
                            ("A TFINN production", ""), ("The Future is Now-Now (PTY) Ltd", "")):
            lab = QLabel(text)
            lab.setAlignment(Qt.AlignCenter)
            if style:
                lab.setStyleSheet(style)
            lay.addWidget(lab)
        site = QLabel("<a href='%s'>%s</a>" % (WEBSITE, WEBSITE.split("//")[1]))
        site.setToolTip("Credits, support and policies")
        site.setOpenExternalLinks(True)
        site.setAlignment(Qt.AlignCenter)
        lay.addWidget(site)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class Window(QMainWindow):
    """A sidebar naming the open vehicle and listing the pages, which all work on that vehicle; above the
    page, its name and the phone it works on; below it, what is running. Only one job talks to the phone
    at a time (State.begin); while one runs the vehicle cannot be switched, and closing the window asks
    first."""
    # the pages in sidebar order: a heading (no page), or a name and its class
    PAGES = (("Overview", OverviewPage), ("Phone", PhonePage),
             ("Car setup", None), ("Maps", MapsPage), ("Music", MusicPage), ("Voices", VoicesPage),
             ("Look", LookPage),
             ("Driving", None), ("Recordings", RecordingsPage), ("Track", TrackPage), ("Log book", LogbookPage),
             ("Convoy", ConvoyPage))

    def __init__(self):
        super().__init__()
        self.setWindowTitle("coldshift.dash")
        self.setMinimumSize(1000, 640)
        self.resize(1240, 800)
        if app_icon():
            self.setWindowIcon(QIcon(app_icon()))
        geometry = QSettings().value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.asked = set()          # vehicles the connect guide has opened for by itself (once each)
        self.build()

    def build(self):
        old = self.centralWidget()
        v = vehicles.current()
        self.vehicle = v
        self.retheme()
        self.state = State()
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._sidebar(v))
        row.addLayout(self._content(), 1)
        page = QWidget()
        page.setLayout(row)
        self.setCentralWidget(page)
        if old is not None:
            old.deleteLater()
        self.setWindowTitle("coldshift.dash — " + (v["name"] if v else "no vehicle"))
        self.state.target_changed.connect(self.show_target)
        self.state.busy_changed.connect(self.show_target)
        self.state.names_changed.connect(self.show_target)
        self.state.progress_changed.connect(self.show_progress)
        self.nav.setCurrentRow(0)
        self.show_target()
        if getattr(self, "busy_dialog", None) is not None:
            self.busy_dialog.deleteLater()          # the one for the vehicle that was open
        self.busy_dialog = BusyDialog(self, self.state)
        self._menus()
        # a vehicle with no phone or card yet: the guide, once, as soon as the window is up
        if v and not self.state.has_target() and v["id"] not in self.asked and "--self-test" not in sys.argv:
            self.asked.add(v["id"])
            QTimer.singleShot(400, self.connect_phone)

    def connect_phone(self):
        if self.state.busy:
            return
        ConnectDialog(self.state, self).exec()

    def _menus(self):
        """The menu bar: what the window's buttons do, with shortcuts, and where each platform expects About
        and Quit (on macOS Qt moves those two into the application's own menu)."""
        bar = self.menuBar()
        bar.clear()

        def add(menu, text, fn, key=None, role=None):
            act = QAction(text, self)
            act.triggered.connect(lambda *_: fn())
            if key:
                act.setShortcut(QKeySequence(key))
            if role is not None:
                act.setMenuRole(role)
            menu.addAction(act)
            return act

        file = bar.addMenu("&File")
        self.switch_act = add(file, "Switch Vehicle…", self.switch, "Ctrl+Shift+O")
        if self.vehicle:
            add(file, forms.SHOW_FOLDER, lambda: forms.show_folder(self.vehicle["folder"]))
        file.addSeparator()
        add(file, "Quit", self.close, QKeySequence.Quit, QAction.QuitRole)
        sync = bar.addMenu("&Sync")
        self.sync_act = add(sync, "Sync Now", lambda: self._overview("sync"), "Ctrl+R")
        self.check_act = add(sync, "Check Again", lambda: self._overview("check"), "Ctrl+Shift+R")
        sync.addSeparator()
        add(sync, "Phone and Connection…", self.show_phone)
        view = bar.addMenu("&View")
        for i, title in enumerate(self.titles):
            add(view, title, lambda t=title: self.go(t), "Ctrl+%d" % ((i + 1) % 10) if i < 10 else None)
        help_ = bar.addMenu("&Help")
        add(help_, "About coldshift.dash", lambda: About(self).exec(), role=QAction.AboutRole)
        add(help_, "coldshift.racing", lambda: QDesktopServices.openUrl(QUrl(WEBSITE)))
        add(help_, "Show Log", self.show_log)

    def _overview(self, what):
        self.go("Overview")
        page = self.stack.widget(self.titles.index("Overview"))
        (page.sync if what == "sync" else page.check)()

    def show_log(self):
        path = paths.log_file()
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write("Nothing has gone wrong yet.\n")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def retheme(self):
        """The window in the open vehicle's accent colour (again after the Interface page changed it)."""
        accent = None
        if self.vehicle and self.vehicle["exists"]:
            try:
                accent = profile.theme(self.vehicle["folder"])["accent"]
            except (OSError, ValueError):
                pass
        theme.apply(accent)

    def _sidebar(self, v):
        car = QLabel()
        car.setAlignment(Qt.AlignCenter)
        if v:
            car.setPixmap(car_icon(v["folder"], 220).pixmap(110, 110))
        name = QLabel(v["name"] if v else "No vehicle")
        name.setObjectName("carname")
        name.setAlignment(Qt.AlignCenter)
        name.setWordWrap(True)
        self.switch_btn = QPushButton("Switch vehicle…")
        self.switch_btn.clicked.connect(self.switch)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setFocusPolicy(Qt.TabFocus)
        self.nav.setIconSize(QSize(8, 8))
        self.stack = QStackedWidget()
        self.titles = []
        self.rows = {}              # a page's name -> its row in the sidebar
        small = QFont()
        small.setPointSizeF(small.pointSizeF() * 0.82)
        small.setCapitalization(QFont.AllUppercase)
        small.setLetterSpacing(QFont.PercentageSpacing, 108)
        for title, cls in self.PAGES:
            it = QListWidgetItem(title)
            if cls is None:
                it.setFlags(Qt.NoItemFlags)
                it.setFont(small)
            else:
                it.setData(Qt.UserRole, self.stack.count())
                it.setIcon(dot("transparent", 8))
                self.rows[title] = self.nav.count()
                page = cls(self.state)
                if cls is OverviewPage:
                    page.open_page.connect(self.go)
                    page.area_changed.connect(self.light)
                self.stack.addWidget(page)
                self.titles.append(title)
            self.nav.addItem(it)
        self.nav.currentItemChanged.connect(self._page)
        folder = QPushButton(forms.SHOW_FOLDER)
        folder.setObjectName("quiet")
        folder.setToolTip("This vehicle's folder: " + (v["folder"] if v else ""))
        folder.setEnabled(bool(v))
        folder.clicked.connect(lambda: forms.show_folder(v["folder"]))
        about = QPushButton("About")
        about.setObjectName("quiet")
        about.clicked.connect(lambda: About(self).exec())
        top = QVBoxLayout()
        top.setContentsMargins(16, 18, 16, 8)
        top.setSpacing(8)
        top.addWidget(car)
        top.addWidget(name)
        top.addWidget(self.switch_btn)
        foot = QVBoxLayout()
        foot.setContentsMargins(10, 4, 10, 12)
        foot.setSpacing(0)
        foot.addWidget(folder)
        foot.addWidget(about)
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(210)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(self.nav, 1)
        lay.addLayout(foot)
        return side

    def _content(self):
        self.title = QLabel()
        self.title.setObjectName("pagetitle")
        self.chip = QPushButton()
        self.chip.setObjectName("chip")
        self.chip.setCursor(Qt.PointingHandCursor)
        self.chip.clicked.connect(self.chip_clicked)
        head = QHBoxLayout()
        head.addWidget(self.title, 1)
        head.addWidget(self.chip)
        # a look at the phone, with the one progress bar, under every page (a sync gets the dialog instead)
        self.busy = forms.muted(QLabel())
        self.busy_bar = QProgressBar()
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedWidth(220)
        self.activity = QFrame()
        self.activity.setObjectName("activity")
        act = QHBoxLayout(self.activity)
        act.setContentsMargins(12, 7, 12, 7)
        act.addWidget(self.busy, 1)
        act.addWidget(self.busy_bar)
        lay = QVBoxLayout()
        lay.setContentsMargins(22, 16, 22, 14)
        lay.setSpacing(10)
        lay.addLayout(head)
        lay.addWidget(self.stack, 1)
        lay.addWidget(self.activity)
        return lay

    def _page(self, item, _before=None):
        if item is None or item.data(Qt.UserRole) is None:
            return
        i = item.data(Qt.UserRole)
        self.stack.setCurrentIndex(i)
        self.title.setText(self.titles[i])
        self.retheme()

    def go(self, title):
        self.nav.setCurrentRow(self.rows[title])

    def light(self, title, colour):
        """The light beside a page in the sidebar: how that part stands against the phone (none: not known)."""
        it = self.nav.item(self.rows[title])
        it.setIcon(dot(colour or "transparent", 8))
        it.setToolTip({theme.GOOD: "Up to date on the phone", theme.WAIT: "Something to sync",
                       forms.WARN: "Could not be checked"}.get(colour, ""))

    def chip_clicked(self):
        """With a phone or card chosen: the Phone page. With none: the guide to connecting one."""
        if self.state.has_target():
            self.show_phone()
        else:
            self.connect_phone()

    def show_phone(self):
        """The Phone page, with its list of phones read again."""
        self.go("Phone")
        self.stack.widget(self.titles.index("Phone")).refresh()

    def show_progress(self):
        self.busy_bar.setRange(*self.state.span)
        self.busy_bar.setValue(self.state.value)

    def show_target(self):
        s = self.state
        if not s.has_target():
            text, colour, tip = "No phone or card chosen", theme.OFF, "Click to connect a phone or its card"
        elif s.connected() is None:
            text, colour, tip = s.label(), theme.OFF, "Looking for it…"
        elif s.connected():
            text, colour, tip = s.label(), theme.GOOD, "Connected when last checked. Click to check again."
        else:
            text, colour, tip = s.label(), theme.WAIT, "Not connected when last checked. Click to check again."
        self.chip.setText(text[0].upper() + text[1:])
        self.chip.setIcon(dot(colour))
        self.chip.setToolTip(tip)
        self.activity.setVisible(s.quiet())
        self.show_progress()
        self.busy.setText("%s…" % (s.busy[0].upper() + s.busy[1:]) if s.busy else "")
        self.switch_btn.setEnabled(not s.busy)
        for act in (getattr(self, "switch_act", None), getattr(self, "sync_act", None), getattr(self, "check_act", None)):
            if act is not None:
                act.setEnabled(not s.busy and (act is self.switch_act or s.has_target()))
        self.switch_btn.setToolTip("Wait for %s to finish" % s.busy if s.busy else "")

    def switch(self):
        if self.state.busy:
            return
        before = vehicles.current()
        if VehiclePicker(self).exec() == QDialog.Accepted or vehicles.current() != before:
            self.build()

    def closeEvent(self, e):
        if self.state.busy and QMessageBox.question(
                self, "Quit", "Still %s. Quitting stops it part-way (what is copied so far stays). Quit anyway?"
                % self.state.busy) != QMessageBox.Yes:
            e.ignore()
            return
        QSettings().setValue("window/geometry", self.saveGeometry())
        e.accept()


def self_test(app):
    """`--self-test`, for the machines that build the app: opens the window on a throwaway vehicle, shows
    every page once and quits, so a build that cannot start is caught where it is made. Only with
    DASHSYNC_CONFIG set, because it makes a vehicle."""
    import tempfile
    if not os.environ.get("DASHSYNC_CONFIG"):
        raise SystemExit("--self-test needs DASHSYNC_CONFIG set to a throwaway folder")
    v = vehicles.create("Self test", os.path.join(tempfile.mkdtemp(prefix="dash-self-test-"), "car"))
    profile.init(v["folder"])
    w = Window()
    w.show()
    for title in w.titles:
        w.go(title)
        app.processEvents()
    QTimer.singleShot(1500, app.quit)
    app.exec()
    QThreadPool.globalInstance().waitForDone(5000)
    print("self-test ok: %d pages, %s" % (len(w.titles), ", ".join(w.titles)))
    shiboken6.delete(w)
    sys.exit(0)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("coldshift.dash")
    app.setOrganizationName("The Future is Now-Now")
    if getattr(sys, "frozen", False):
        keep_log()
    if app_icon():
        app.setWindowIcon(QIcon(app_icon()))
    theme.apply()
    if "--self-test" in sys.argv:
        self_test(app)
    # the vehicle first: everything in the window belongs to one
    picker = VehiclePicker(first=not vehicles.all())
    chosen = picker.exec() == QDialog.Accepted
    shiboken6.delete(picker)
    if not chosen:
        return
    w = Window()
    w.show()
    code = app.exec()
    # let background jobs (a status check, an adb listing) finish, then take the window down while
    # Qt is still whole: left to Python's shutdown, objects that reference each other are freed twice
    QThreadPool.globalInstance().waitForDone(5000)
    shiboken6.delete(w)
    sys.exit(code)


if __name__ == "__main__":
    main()
