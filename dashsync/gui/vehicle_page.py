"""Vehicle page: the vehicle's look in the app (dashsync/profile.py) with previews: the title bar (its
title and badges), the background behind every page, the splash (background, logo and its effect), the
Media page logo and the car picture (Sensors' tyres and map marker). Every picture can be replaced, put back
to the built-in one, or left out. Each section has its preview on the left and its controls on the right."""
import math
import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QImage, QLinearGradient, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListView,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from .. import paths, profile
from . import forms
from .syncbar import look_syncbar

MAP_BG = QColor("#262a2e")         # about the dark map theme's land colour
PANEL_BG = QColor("#0b1424")       # the app's panels
PICTURES = "Pictures (*.png *.jpg *.jpeg *.webp)"
PLAY_FOR = 6.0                     # seconds the splash preview plays before holding still


def _pixmap(png):
    p = QPixmap()
    p.loadFromData(png)
    return p


def placeholder(w, h, text):
    """An empty preview: a framed dark box with light text (readable in light and dark mode)."""
    out = QPixmap(w, h)
    out.fill(PANEL_BG)
    p = QPainter(out)
    p.setPen(QColor(255, 255, 255, 60))
    p.drawRect(0, 0, w - 1, h - 1)
    p.setPen(QColor(200, 210, 225))
    p.drawText(out.rect(), Qt.AlignCenter | Qt.TextWordWrap, text)
    p.end()
    return out


def section(title, preview, controls):
    """A group box with the preview on the left and the controls (a layout) beside it."""
    box = QGroupBox(title)
    row = QHBoxLayout(box)
    row.addWidget(preview, 0, Qt.AlignTop)
    row.addSpacing(12)
    row.addLayout(controls, 1)
    return box


def halos(logo_path):
    """The glow's two halos as the app makes them (Splash.java): the logo's shape blurred wide and blurred
    close, in near-white light, each grown by its blur. [(QImage, offset in logo pixels)]."""
    from PIL import Image, ImageFilter
    im = Image.open(logo_path).convert("RGBA")
    out = []
    for radius in (max(16, im.height / 5), max(6, im.height / 16)):
        pad = int(radius * 2)
        alpha = Image.new("L", (im.width + 2 * pad, im.height + 2 * pad), 0)
        alpha.paste(im.getchannel("A"), (pad, pad))
        # Android's blur radius is about 1.7 times a Gaussian's sigma
        alpha = alpha.filter(ImageFilter.GaussianBlur(radius / 1.7))
        light = Image.new("RGBA", alpha.size, (236, 244, 255, 0))
        light.putalpha(alpha)
        out.append((QImage.fromData(profile.png_bytes(light)), -pad))
    return out


class SplashPreview(QWidget):
    """The splash as the app plays it (Splash.java), small: background, logo, effect. It plays for a few
    seconds when shown or changed, then holds still (no timer runs while it is hidden)."""
    W, H = 448, 252

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.W, self.H)
        self.bg = self.logo = None
        self.halos = []
        self.effect, self.position = "shine", "left"
        self.t0 = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def show_profile(self, bg, logo, effect, position):
        self.bg = QPixmap(bg) if bg else None
        self.logo = QImage(logo) if logo else None
        self.effect, self.position = effect, position
        self.halos = halos(logo) if logo and effect == "glow" else []
        self.replay()

    def replay(self):
        self.t0 = time.monotonic()
        if self.isVisible():
            self.timer.start(40)
        self.update()

    def _tick(self):
        if time.monotonic() - self.t0 > PLAY_FOR:
            self.timer.stop()
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self.replay()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.scale(self.W / 1280, self.H / 720)
        p.fillRect(0, 0, 1280, 720, Qt.black)
        if self.bg:
            p.drawPixmap(QRectF(0, 0, 1280, 720), self.bg, QRectF(self.bg.rect()))
        if self.logo and not self.logo.isNull():
            t = min(time.monotonic() - self.t0, PLAY_FOR) * 1000
            self._logo(p, t if self.timer.isActive() else 99999)
        p.end()

    def _logo(self, p, t):
        area = QRectF(430, 240, 420, 240) if self.position == "centre" else QRectF(110, 65, 420, 240)
        k = min(area.width() / self.logo.width(), area.height() / self.logo.height())
        w, h = self.logo.width() * k, self.logo.height() * k
        box = QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)
        img = self.logo
        if self.effect == "rise":
            f = min(1.0, t / 1100)
            ease = 1 - (1 - f) ** 3
            s = 0.9 + 0.1 * ease
            box = QRectF(box.center().x() - w * s / 2, box.center().y() - h * s / 2 + 24 * (1 - ease), w * s, h * s)
            p.setOpacity(ease)
        elif self.effect == "glow":
            # light around the logo, breathing slowly (held at its middle once the preview stops)
            breath = 0.5 + 0.5 * math.sin(2 * math.pi * t / 2400) if t < 99999 else 0.5
            for (halo, off), (base, swing) in zip(self.halos, ((120, 90), (90, 70))):
                p.setOpacity((base + swing * breath) / 255)
                p.drawImage(QRectF(box.left() + off * k, box.top() + off * k, halo.width() * k, halo.height() * k), halo)
            p.setOpacity(1)
        elif self.effect == "shine" and t < 99999:
            phase = (t % 2400) / 1200
            if phase < 1:
                img = QImage(self.logo.convertToFormat(QImage.Format_ARGB32_Premultiplied))
                ip = QPainter(img)
                ip.setCompositionMode(QPainter.CompositionMode_SourceAtop)
                bw = img.width() * 0.22
                x = -bw * 2 + (img.width() + bw * 4) * phase
                g = QLinearGradient(x - bw, 0, x + bw, img.height() * 0.4)
                g.setColorAt(0, QColor(255, 255, 255, 0))
                g.setColorAt(0.5, QColor(255, 255, 255, 136))
                g.setColorAt(1, QColor(255, 255, 255, 0))
                ip.fillRect(img.rect(), g)
                ip.end()
        p.drawImage(box, img)
        p.setOpacity(1)


class ImageButtons(QWidget):
    """Choose… / Built-in / None for one of the profile's pictures. A widget, not a layout subclass: a
    Python-owned layout kept alive by its button connections is deleted twice when the window closes."""
    def __init__(self, page, key):
        super().__init__()
        self.page, self.key = page, key
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        for text, fn, tip in (("Choose…", self.choose, "Use a picture of your own"),
                              ("Built-in", self.builtin, "Back to the app's own"),
                              ("None", self.clear, "Show nothing here")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self.page, "Picture", "", PICTURES)
        if path:
            self.page.change(lambda v: profile.set_image(v, self.key, path))

    def _ok_to_drop(self):
        v = self.page.vehicle()
        return not (v and profile.is_custom(v, self.key)) or QMessageBox.question(
            self.page, "Replace your picture", "This drops the picture you chose for this place (keep a copy if you "
            "want it back). Go ahead?") == QMessageBox.Yes

    def builtin(self):
        if self._ok_to_drop():
            self.page.change(lambda v: profile.builtin_image(v, self.key))

    def clear(self):
        if self._ok_to_drop():
            self.page.change(lambda v: profile.clear_image(v, self.key))


class VehiclePage(QWidget):
    """`syncbar`: the Look page's, shared with its other tab (without one the page has its own)."""
    def __init__(self, state, syncbar=None):
        super().__init__()
        self.state = state
        body = QWidget()
        page = QVBoxLayout(body)

        # title bar: the preview across the top, then title and badges
        top = QGroupBox("Title bar")
        self.titlebar = QLabel()
        self.titlebar.setMinimumHeight(40)
        # it follows the space it is given instead of asking for the window's width (a sideways scrollbar)
        self.titlebar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Shown after the badges, e.g. PEPPERMINT CRISP (empty for none)")
        self.title.editingFinished.connect(self._title)
        self.badge_list = QListWidget()
        self.badge_list.setViewMode(QListView.IconMode)
        self.badge_list.setFlow(QListView.LeftToRight)
        self.badge_list.setWrapping(False)
        self.badge_list.setMovement(QListView.Static)
        self.badge_list.setFixedHeight(84)
        self.badge_list.setIconSize(QSize(140, 42))
        pal = self.badge_list.palette()          # the app's dark bar, so white badges show
        pal.setColor(pal.ColorRole.Base, QColor("#060c18"))
        self.badge_list.setPalette(pal)
        self.badge_list.currentRowChanged.connect(lambda *_: self._buttons())
        row = QHBoxLayout()
        self.badge_btns = {}
        for text, fn in (("Add badge…", self.add_badge), ("Remove", self.remove_badge),
                         ("◀ Move left", lambda: self.move_badge(-1)), ("Move right ▶", lambda: self.move_badge(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.badge_btns[text] = b
        row.addStretch()
        f = forms.form()
        f.addRow("Title", self.title)
        lay = QVBoxLayout(top)
        lay.addWidget(self.titlebar)
        lay.addLayout(f)
        lay.addWidget(QLabel("Badges, left to right:"))
        lay.addWidget(self.badge_list)
        lay.addLayout(row)
        lay.addWidget(forms.note("Each badge is its own picture (a PNG with a transparent background works best), "
                                 "shown 42 px high: the make's logo, the model, a trim badge."))
        page.addWidget(top)

        # background
        self.background = QLabel()
        self.background.setFixedSize(320, 180)
        c = QVBoxLayout()
        c.addWidget(ImageButtons(self, "background"))
        c.addWidget(forms.note("Behind every page. A photo of the car works well; it is cropped to fill the screen "
                               "(1280 x 720) and the app darkens it under its panels."))
        c.addStretch()
        page.addWidget(section("Background", self.background, c))

        # splash
        self.splash = SplashPreview()
        replay = QPushButton("▶ Replay")
        replay.clicked.connect(lambda: self.splash.replay())
        self.effect = QComboBox()
        for name, label in (("shine", "Shine: light sweeps across the logo"), ("glow", "Glow: a pulsing halo"),
                            ("rise", "Rise: fades in and grows into place"), ("none", "None")):
            self.effect.addItem(label, name)
        self.position = QComboBox()
        self.position.addItem("Top left", "left")
        self.position.addItem("Centre", "centre")
        self.effect.activated.connect(lambda *_: self.change(lambda v: profile.set_options(v, effect=self.effect.currentData())))
        self.position.activated.connect(lambda *_: self.change(lambda v: profile.set_options(v, position=self.position.currentData())))
        c = QVBoxLayout()
        f = forms.form()
        f.addRow("Logo effect", self.effect)
        f.addRow("Logo position", self.position)
        c.addLayout(f)
        c.addWidget(replay, 0, Qt.AlignLeft)
        c.addWidget(QLabel("Splash background"))
        c.addWidget(ImageButtons(self, "splash.background"))
        c.addWidget(QLabel("Logo"))
        c.addWidget(ImageButtons(self, "splash.logo"))
        c.addWidget(forms.note("The logo is best as a PNG with a transparent background; the effect follows its shape."))
        c.addStretch()
        page.addWidget(section("Splash (when the app starts)", self.splash, c))

        # media page logo
        self.wordmark = QLabel()
        self.wordmark.setFixedSize(320, 68)
        c = QVBoxLayout()
        c.addWidget(ImageButtons(self, "wordmark"))
        c.addWidget(forms.note("On the Media page while nothing plays."))
        c.addStretch()
        page.addWidget(section("Media page logo", self.wordmark, c))

        # car picture
        self.tpms = QLabel()
        self.tpms.setFixedSize(200, 200)
        self.map = QLabel()
        self.map.setFixedSize(200, 200)
        pics = QWidget()
        pl = QHBoxLayout(pics)
        pl.setContentsMargins(0, 0, 0, 0)
        for pic, cap in ((self.tpms, "Sensors: tyres"), (self.map, "Your position on the map")):
            col = QVBoxLayout()
            col.addWidget(pic)
            col.addWidget(forms.note(cap))
            pl.addLayout(col)
        c = QVBoxLayout()
        c.addWidget(ImageButtons(self, "car"))
        c.addWidget(forms.note("A view of the car from above, front pointing up, on a transparent background (a PNG "
                               "with the car cut out). It is cropped to the car and centred, so any size works."))
        c.addStretch()
        page.addWidget(section("Car picture", pics, c))
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

        state.target_changed.connect(self._buttons)
        self.refresh()

    def vehicle(self):
        return paths.load_config().get("workspace")

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self.syncbar.recheck()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        v = self.vehicle()
        if v:
            self.titlebar.setPixmap(self._titlebar(v, profile.load(v)))

    def change(self, fn):
        """Applies a change to the profile, then shows it."""
        v = self.vehicle()
        if not v:
            return
        try:
            fn(v)
        except (OSError, ValueError) as e:
            forms.error(self, "Vehicle", str(e))
        self.refresh()
        self.syncbar.recheck()

    def refresh(self):
        v = self.vehicle()
        if not v:
            self._buttons()
            return
        prof = profile.load(v)
        if not self.title.hasFocus():
            self.title.setText(prof.get("title", ""))
        row = self.badge_list.currentRow()
        self.badge_list.clear()
        for b in profile.badges(v):
            pix = QPixmap(b).scaledToHeight(42, Qt.SmoothTransformation)
            it = QListWidgetItem(QIcon(pix), "")
            it.setSizeHint(pix.size() + QSize(12, 12))
            self.badge_list.addItem(it)
        self.badge_list.setCurrentRow(min(row, self.badge_list.count() - 1))
        self.titlebar.setPixmap(self._titlebar(v, prof))
        bg = profile.image(v, "background")
        self.background.setPixmap(self._background(bg) if bg else placeholder(320, 180, "No background\n(black)"))
        self.effect.setCurrentIndex(max(0, self.effect.findData(prof["splash"]["effect"])))
        self.position.setCurrentIndex(max(0, self.position.findData(prof["splash"]["position"])))
        self.splash.show_profile(profile.image(v, "splash.background"), profile.image(v, "splash.logo"),
                                 prof["splash"]["effect"], prof["splash"]["position"])
        wm = profile.image(v, "wordmark")
        if wm:
            out = QPixmap(320, 68)
            out.fill(PANEL_BG)
            pix = QPixmap(wm).scaled(304, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p = QPainter(out)
            p.drawPixmap((320 - pix.width()) // 2, (68 - pix.height()) // 2, pix)
            p.end()
            self.wordmark.setPixmap(out)
        else:
            self.wordmark.setPixmap(placeholder(320, 68, "No logo"))
        car = profile.image(v, "car")
        self.tpms.setPixmap(self._tpms(car) if car else placeholder(200, 200, "No car picture"))
        self.map.setPixmap(self._map(car) if car else placeholder(200, 200, "A blue dot\n(no car picture)"))
        self._buttons()

    def _titlebar(self, v, prof):
        """The app's title bar (UI.topBar) at full size, scaled to the page's width."""
        out = QPixmap(1280, 54)
        out.fill(QColor("#060c18"))
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        bg = profile.image(v, "background")
        if bg:
            pix = QPixmap(bg)
            p.drawPixmap(QRectF(0, 0, 1280, 54), pix, QRectF(0, 0, pix.width(), pix.height() * 54 / 720))
        g = QLinearGradient(0, 0, 0, 54)
        g.setColorAt(0, QColor(6, 12, 24, 0xf8))
        g.setColorAt(1, QColor(6, 12, 24, 0xc7))
        p.fillRect(0, 0, 1280, 54, g)
        x = 16
        for b in profile.badges(v):
            pix = QPixmap(b)
            w = pix.width() * 42 / pix.height()
            p.drawPixmap(QRectF(x, 6, w, 42), pix, QRectF(pix.rect()))
            x += w + 10
        # the app's font where this computer has it (asking for a missing family makes Qt search and warn)
        font = QFont("Roboto") if "Roboto" in QFontDatabase.families() else QFont()
        font.setPixelSize(17)
        font.setItalic(True)
        p.setFont(font)
        p.setPen(QColor(0x93, 0xa9, 0xc8))
        if prof.get("title"):
            p.drawText(int(x + 8), 32, prof["title"])
        font.setItalic(False)
        font.setBold(True)
        font.setPixelSize(28)
        p.setFont(font)
        p.setPen(Qt.white)
        p.drawText(QRectF(900, 0, 360, 54), Qt.AlignRight | Qt.AlignVCenter, time.strftime("%H:%M"))
        p.end()
        width = max(300, min(1280, self.titlebar.width() if self.titlebar.width() > 50 else self.width() - 100))
        return out.scaledToWidth(width, Qt.SmoothTransformation)

    def _background(self, bg):
        out = QPixmap(320, 180)
        out.fill(QColor("#05070d"))
        p = QPainter(out)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(out.rect(), QPixmap(bg))
        p.fillRect(out.rect(), QColor(5, 8, 16, 80))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(7, 14, 27, 219))                    # a panel, as the pages put on it
        p.drawRoundedRect(QRectF(13, 25, 142, 125), 6, 6)
        p.end()
        return out

    def _tpms(self, src):
        out = QPixmap(200, 200)
        out.fill(PANEL_BG)
        car = QPixmap(src).scaled(186, 186, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p = QPainter(out)
        p.drawPixmap((200 - car.width()) // 2, (200 - car.height()) // 2, car)
        p.end()
        return out

    def _map(self, src):
        """The marker as the app draws it, on map-coloured ground with a road, heading up and at an angle."""
        out = QPixmap(200, 200)
        out.fill(MAP_BG)
        marker = _pixmap(profile.png_bytes(profile.marker(src)))
        p = QPainter(out)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(36, 0, 34, 200, QColor("#8a8f94"))
        p.fillRect(46, 0, 14, 200, QColor(47, 123, 255, 217))          # the route line
        p.drawPixmap(53 - marker.width() // 2, 100 - marker.height() // 2, marker)
        turned = marker.transformed(QTransform().rotate(40), Qt.SmoothTransformation)
        p.drawPixmap(145 - turned.width() // 2, 100 - turned.height() // 2, turned)
        p.end()
        return out

    def _buttons(self):
        v = self.vehicle()
        n, i = self.badge_list.count(), self.badge_list.currentRow()
        self.badge_btns["Add badge…"].setEnabled(bool(v))
        self.badge_btns["Remove"].setEnabled(bool(v) and i >= 0)
        self.badge_btns["◀ Move left"].setEnabled(bool(v) and i > 0)
        self.badge_btns["Move right ▶"].setEnabled(bool(v) and 0 <= i < n - 1)

    def _title(self):
        v = self.vehicle()
        if v and self.title.text().strip() != profile.load(v).get("title", ""):
            self.change(lambda v: profile.set_options(v, title=self.title.text()))

    def add_badge(self):
        path, _ = QFileDialog.getOpenFileName(self, "Badge", "", PICTURES)
        if path:
            self.change(lambda v: profile.add_badge(v, path))
            self.badge_list.setCurrentRow(self.badge_list.count() - 1)

    def remove_badge(self):
        i = self.badge_list.currentRow()
        if i >= 0:
            self.change(lambda v: profile.remove_badge(v, i))

    def move_badge(self, d):
        i = self.badge_list.currentRow()
        if i >= 0:
            self.change(lambda v: profile.move_badge(v, i, d))
            self.badge_list.setCurrentRow(i + d)
