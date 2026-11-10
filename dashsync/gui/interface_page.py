"""Interface page: the app's colours and which pages its tab bar shows (and in what order), with a
preview of the car screen in those colours. Kept in the vehicle's profile (dashsync/profile.py)."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import paths, profile
from . import forms, theme
from .syncbar import look_syncbar

PAGE = Qt.UserRole
PREVIEW_W = 560


def _c(hex_, alpha=255):
    c = QColor(hex_)
    c.setAlpha(alpha)
    return c


def _mix(a, b, k):
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() * (1 - k) + b.red() * k), round(a.green() * (1 - k) + b.green() * k),
                  round(a.blue() * (1 - k) + b.blue() * k))


def _scale(hex_, k):
    c = QColor(hex_)
    return QColor(min(255, round(c.red() * k)), min(255, round(c.green() * k)), min(255, round(c.blue() * k)))


class InterfacePage(QWidget):
    """`syncbar`: the Look page's, shared with its other tab (without one the page has its own)."""
    def __init__(self, state, syncbar=None):
        super().__init__()
        self.state = state
        body = QWidget()
        page = QVBoxLayout(body)

        prev = QGroupBox("Preview")
        self.preview = QLabel()
        self.preview.setFixedWidth(PREVIEW_W)
        lay = QVBoxLayout(prev)
        lay.addWidget(self.preview)
        lay.addWidget(forms.note("The car screen in these colours: title bar, a panel, a button, the active one, "
                                 "a highlight, and the tab bar with the chosen pages."))
        lay.addStretch()
        top = QHBoxLayout()
        top.addWidget(prev, 0, Qt.AlignTop)
        side = QVBoxLayout()
        top.addLayout(side, 1)
        page.addLayout(top)
        row = side
        cols = QGroupBox("Colours")
        cl = QVBoxLayout(cols)
        self.swatches = {}
        for key in profile.THEME:
            r = QHBoxLayout()
            b = QPushButton()
            b.setFixedSize(46, 26)
            b.clicked.connect(lambda _=False, k=key: self.pick(k))
            self.swatches[key] = b
            r.addWidget(b)
            r.addWidget(QLabel(profile.THEME_NAMES[key]), 1)
            cl.addLayout(r)
        cl.addWidget(QLabel("Accent presets:"))
        pr = QGridLayout()
        for i, (name, hex_) in enumerate(profile.PRESETS.items()):
            b = QPushButton(name)
            b.setToolTip(hex_)
            b.clicked.connect(lambda _=False, h=hex_: self.change(lambda v: profile.set_theme(v, accent=h)))
            pr.addWidget(b, i // 4, i % 4)
        cl.addLayout(pr)
        reset = QPushButton("Reset colours")
        reset.clicked.connect(lambda: self.change(lambda v: profile.set_theme(v, reset=True)))
        cl.addWidget(reset, 0, Qt.AlignLeft)
        cl.addStretch()
        row.addWidget(cols)

        pg = QGroupBox("Pages")
        pl = QVBoxLayout(pg)
        self.pages = QListWidget()
        self.pages.setDragDropMode(QAbstractItemView.InternalMove)
        self.pages.itemChanged.connect(lambda *_: self.save_pages())
        self.pages.model().rowsMoved.connect(lambda *_: self.save_pages())
        pl.addWidget(self.pages, 1)
        pl.addWidget(forms.note("Tick the pages the car screen shows; drag to change their order. Settings is always "
                                "there, last, so the setup can always be reached. A hidden page's feature keeps "
                                "working (navigation, the dashcam)."))
        row.addWidget(pg, 1)
        page.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)     # the page follows the width
        self.syncbar = syncbar if syncbar is not None else look_syncbar(state)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.addWidget(scroll, 1)
        if syncbar is None:
            outer.addWidget(self.syncbar)
        self.refresh()

    def vehicle(self):
        return paths.load_config().get("workspace")

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self.syncbar.recheck()

    def change(self, fn):
        v = self.vehicle()
        if not v:
            return
        try:
            fn(v)
        except (OSError, ValueError) as e:
            forms.error(self, "Interface", str(e))
        self.refresh()
        self.syncbar.recheck()
        theme.apply(profile.theme(v)["accent"])        # this window wears the vehicle's accent too

    def pick(self, key):
        v = self.vehicle()
        c = QColorDialog.getColor(QColor(profile.theme(v)[key]), self, profile.THEME_NAMES[key])
        if c.isValid():
            self.change(lambda v: profile.set_theme(v, **{key: c.name()}))

    def refresh(self):
        v = self.vehicle()
        if not v:
            return
        t = profile.theme(v)
        for key, b in self.swatches.items():
            b.setStyleSheet("background: %s; border: 1px solid #888; border-radius: 4px" % t[key])
            b.setToolTip(t[key])
        shown = profile.pages(v)
        self.pages.blockSignals(True)
        self.pages.clear()
        names = dict(profile.PAGES)
        for p in shown + [p for p, _ in profile.PAGES if p not in shown]:
            it = QListWidgetItem(names[p])
            it.setData(PAGE, p)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            it.setCheckState(Qt.Checked if p in shown else Qt.Unchecked)
            self.pages.addItem(it)
        fixed = QListWidgetItem("Settings (always shown, last)")
        fixed.setFlags(Qt.ItemIsEnabled)
        self.pages.addItem(fixed)
        self.pages.blockSignals(False)
        self.draw_preview()

    def save_pages(self):
        shown = []
        for i in range(self.pages.count()):
            it = self.pages.item(i)
            if it.data(PAGE) and it.checkState() == Qt.Checked:
                shown.append(it.data(PAGE))
        v = self.vehicle()
        if v and shown != profile.pages(v):
            self.change(lambda v: profile.set_pages(v, shown))

    def draw_preview(self):
        """A sketch of the car screen (UI.java) in the vehicle's colours, scaled to the page."""
        v = self.vehicle()
        t = profile.theme(v)
        accent, panel, text, sub, high = (t[k] for k in ("accent", "panel", "text", "subtext", "highlight"))
        out = QPixmap(1280, 720)
        out.fill(QColor("#05070d"))
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        bg = profile.image(v, "background")
        if bg:
            p.drawPixmap(QRectF(0, 0, 1280, 720), QPixmap(bg), QRectF(QPixmap(bg).rect()))
        p.fillRect(0, 0, 1280, 720, QColor(5, 8, 16, 120))
        font = QFont("Roboto") if "Roboto" in QFontDatabase.families() else QFont()

        def write(s, x, y, size, colour, bold=False, italic=False, align=Qt.AlignLeft):
            font.setPixelSize(size)
            font.setBold(bold)
            font.setItalic(italic)
            p.setFont(font)
            p.setPen(colour)
            if align == Qt.AlignLeft:
                p.drawText(int(x), int(y), s)
            else:
                p.drawText(QRectF(x - 300, y - size, 600, size * 1.4), Qt.AlignHCenter, s)

        def button(r, active):
            if active:
                g = QLinearGradient(0, r.top(), 0, r.bottom())
                g.setColorAt(0, _scale(accent, 0.78))
                g.setColorAt(1, _scale(accent, 0.42))
                p.setBrush(g)
                p.setPen(_mix(accent, "#ffffff", 0.15))
            else:
                p.setBrush(_c(_mix(panel, accent, 0.12).name(), 0xf2))
                p.setPen(_c(accent, 0x38))
            p.drawRoundedRect(r, 12, 12)

        # title bar
        g = QLinearGradient(0, 0, 0, 54)
        g.setColorAt(0, QColor(6, 12, 24, 0xf8))
        g.setColorAt(1, QColor(6, 12, 24, 0xc7))
        p.fillRect(0, 0, 1280, 54, g)
        p.fillRect(0, 53, 1280, 1, _c(accent, 0x47))
        x = 16
        for b in profile.badges(v):
            pix = QPixmap(b)
            w = pix.width() * 42 / pix.height()
            p.drawPixmap(QRectF(x, 6, w, 42), pix, QRectF(pix.rect()))
            x += w + 10
        write(profile.load(v).get("title", ""), x + 8, 32, 17, QColor(sub), italic=True)
        write("12:34", 1180, 36, 28, QColor("#ffffff"), bold=True)
        # a panel with some of what pages show
        p.setBrush(_c(panel, 0xdb))
        p.setPen(_c(accent, 0x38))
        p.drawRoundedRect(QRectF(14, 68, 1252, 557), 14, 14)
        write("Now playing", 40, 120, 30, QColor("#ffffff"), bold=True)
        write("Secondary text looks like this", 40, 156, 17, QColor(sub))
        write("Text in lists and buttons", 40, 196, 20, QColor(text))
        button(QRectF(40, 240, 220, 70), False)
        write("Button", 150, 286, 22, QColor(text), align=Qt.AlignHCenter)
        button(QRectF(280, 240, 220, 70), True)
        write("Active", 390, 286, 22, QColor("#ffffff"), align=Qt.AlignHCenter)
        p.setBrush(_c(panel, 0xf2))
        p.setPen(_c(high, 0xaa))
        p.drawRoundedRect(QRectF(520, 250, 160, 50), 10, 10)
        write("MARK", 600, 284, 20, QColor(high), bold=True, align=Qt.AlignHCenter)
        # a slider
        p.setPen(Qt.NoPen)
        p.setBrush(_c(accent, 0x55))
        p.drawRoundedRect(QRectF(40, 360, 600, 10), 5, 5)
        p.setBrush(QColor(accent))
        p.drawRoundedRect(QRectF(40, 360, 380, 10), 5, 5)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(408, 351, 28, 28))
        # tab bar
        p.fillRect(0, 633, 1280, 87, QColor(5, 9, 18, 0xf0))
        p.fillRect(0, 633, 1280, 1, _c(accent, 0x33))
        names = dict(profile.PAGES)
        tabs = [names[x] for x in profile.pages(v)] + ["Settings"]
        n = len(tabs)
        tw = (1280 - 8 * (n + 1)) / n
        for i, label in enumerate(tabs):
            r = QRectF(8 + i * (tw + 8), 642, tw, 70)
            button(r, i == 0)
            write(label, r.center().x(), 685, 21, QColor("#ffffff") if i == 0 else QColor(sub), align=Qt.AlignHCenter)
        p.end()
        pix = out.scaledToWidth(PREVIEW_W, Qt.SmoothTransformation)
        self.preview.setFixedHeight(pix.height())
        self.preview.setPixmap(pix)
