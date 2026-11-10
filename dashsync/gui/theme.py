"""The window's look: the car app's dark blue, with the open vehicle's accent colour on the main buttons,
the selection and the progress bars. Colours go in the palette (so widgets that read it, like the muted
notes, follow) and the shapes in one stylesheet."""
import os

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from .. import paths

ACCENT = "#2f7bff"
BG = "#0a111e"              # the window
SIDE = "#070d18"            # the sidebar
CARD = "#101a2b"            # group boxes
FIELD = "#060b15"           # lists, tables and text fields
LINE = "#1e2c44"            # borders
BUTTON = "#18243a"
BUTTON_LINE = "#2a3a57"
TEXT = "#e8eef7"
SUB = "#93a9c8"             # secondary text: about 7:1 on a card
OFF = "#56657d"             # disabled text
GOOD, WAIT = "#46d17a", "#e3b341"


def mix(a, b, k):
    """Colour a with k of colour b mixed in, as "#rrggbb"."""
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() * (1 - k) + b.red() * k), round(a.green() * (1 - k) + b.green() * k),
                  round(a.blue() * (1 - k) + b.blue() * k)).name()


def on(colour):
    """Text that reads on a colour: white, or near black on a light one."""
    c = QColor(colour)
    return "#06101f" if (c.red() * 299 + c.green() * 587 + c.blue() * 114) / 1000 > 150 else "#ffffff"


def usable(accent):
    """The vehicle's accent, unless it is too dark to see on this window (then the default)."""
    c = QColor(accent or ACCENT)
    if not c.isValid() or (c.red() * 299 + c.green() * 587 + c.blue() * 114) / 1000 < 60:
        return ACCENT
    return c.name()


def palette(accent):
    p = QPalette()
    for role, colour in ((QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, FIELD),
                         (QPalette.AlternateBase, mix(FIELD, CARD, 0.5)), (QPalette.Text, TEXT),
                         (QPalette.Button, BUTTON), (QPalette.ButtonText, TEXT), (QPalette.BrightText, "#ffffff"),
                         (QPalette.Highlight, mix(FIELD, accent, 0.45)), (QPalette.HighlightedText, "#ffffff"),
                         (QPalette.PlaceholderText, SUB), (QPalette.ToolTipBase, CARD), (QPalette.ToolTipText, TEXT),
                         (QPalette.Link, accent), (QPalette.Light, BUTTON_LINE), (QPalette.Midlight, LINE),
                         (QPalette.Mid, LINE), (QPalette.Dark, "#04070d"), (QPalette.Shadow, "#000000")):
        p.setColor(role, QColor(colour))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(OFF))
    return p


def tick(colour):
    """A check mark in that colour as a picture file (a stylesheet can only draw one from a file)."""
    path = os.path.join(paths.cache_dir(), "tick-%s.png" % colour.lstrip("#"))
    if not os.path.exists(path):
        pix = QPixmap(30, 30)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(colour), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QPointF(7, 16), QPointF(13, 21), QPointF(23, 9)])
        p.end()
        pix.save(path)
    return path.replace(os.sep, "/")


def sheet(accent):
    c = dict(accent=accent, tick=tick(on(accent)), on=on(accent), accent_hi=mix(accent, "#ffffff", 0.14), accent_lo=mix(accent, "#000000", 0.18),
             pick=mix(FIELD, accent, 0.45), side_pick=mix(SIDE, accent, 0.30), hover=mix(SIDE, "#ffffff", 0.06),
             bg=BG, side=SIDE, card=CARD, field=FIELD, line=LINE, button=BUTTON, button_line=BUTTON_LINE,
             button_hi=mix(BUTTON, "#ffffff", 0.07), button_lo=mix(BUTTON, "#000000", 0.2), text=TEXT, sub=SUB, off=OFF)
    return """
QToolTip { background: %(card)s; color: %(text)s; border: 1px solid %(button_line)s; padding: 4px 6px; }

QGroupBox { background: %(card)s; border: 1px solid %(line)s; border-radius: 10px; margin-top: 26px;
            padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 2px; top: 5px; color: %(sub)s; }

QPushButton { background: %(button)s; color: %(text)s; border: 1px solid %(button_line)s; border-radius: 6px;
              padding: 5px 14px; min-height: 18px; }
QPushButton:hover { background: %(button_hi)s; }
QPushButton:pressed { background: %(button_lo)s; }
QPushButton:default { background: %(accent)s; border-color: %(accent)s; color: %(on)s; font-weight: 600; }
QPushButton:default:hover { background: %(accent_hi)s; border-color: %(accent_hi)s; }
QPushButton:default:pressed { background: %(accent_lo)s; border-color: %(accent_lo)s; }
QPushButton:disabled, QPushButton:default:disabled { background: transparent; color: %(off)s; border-color: %(line)s;
                                                     font-weight: 400; }

QLineEdit, QPlainTextEdit, QTextEdit { background: %(field)s; color: %(text)s; border: 1px solid %(line)s;
                                       border-radius: 6px; padding: 4px 8px; selection-background-color: %(pick)s; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus { border-color: %(accent)s; }
QLineEdit:disabled { color: %(off)s; }

QAbstractItemView { background: %(field)s; border: 1px solid %(line)s; border-radius: 4px; outline: 0;
                    selection-background-color: %(pick)s; selection-color: #ffffff; }
QTreeView::item { padding: 3px 0; }
QTableView { gridline-color: %(line)s; }
QHeaderView { background: transparent; }
QHeaderView::section { background: %(card)s; color: %(sub)s; border: 0; border-bottom: 1px solid %(line)s;
                       padding: 5px 8px; }
QTableCornerButton::section { background: %(card)s; border: 0; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; background: %(field)s; border: 1px solid %(sub)s; border-radius: 4px; }
QCheckBox::indicator:hover { border-color: %(text)s; }
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; image: url("%(tick)s"); }
QCheckBox::indicator:disabled { border-color: %(line)s; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: %(button_line)s; border-radius: 3px; }
QScrollBar::handle:vertical { min-height: 30px; }
QScrollBar::handle:horizontal { min-width: 30px; }
QScrollBar::handle:hover { background: %(sub)s; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QTabWidget::pane { border: 0; border-top: 1px solid %(line)s; }
QTabBar::tab { background: transparent; color: %(sub)s; padding: 7px 16px; border: 0;
               border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: %(text)s; }
QTabBar::tab:selected { color: %(text)s; border-bottom-color: %(accent)s; }

QProgressBar { background: %(button)s; border: 0; border-radius: 3px; max-height: 6px; color: transparent; }
QProgressBar::chunk { background: %(accent)s; border-radius: 3px; }

QSplitter::handle { background: transparent; }

QMenuBar { background: %(side)s; border-bottom: 1px solid %(line)s; }
QMenuBar::item { padding: 5px 10px; background: transparent; }
QMenuBar::item:selected { background: %(pick)s; }
QMenu::separator { height: 1px; background: %(line)s; margin: 4px 8px; }
QMenu::item:disabled { color: %(off)s; }
QMenu { background: %(card)s; border: 1px solid %(button_line)s; padding: 4px; }
QMenu::item { padding: 5px 18px; border-radius: 4px; }
QMenu::item:selected { background: %(pick)s; }

QFrame#side { background: %(side)s; border: 0; border-right: 1px solid %(line)s; }
QLabel#carname { font-size: 15px; font-weight: 600; }
QLabel#pagetitle { font-size: 22px; font-weight: 600; }
QListWidget#nav { background: transparent; border: 0; border-radius: 0; }
QListWidget#nav::item { color: %(sub)s; padding: 7px 12px; margin: 1px 10px; border-radius: 6px; }
QListWidget#nav::item:hover { background: %(hover)s; color: %(text)s; }
QListWidget#nav::item:selected { background: %(side_pick)s; color: #ffffff; }
QListWidget#nav::item:disabled { color: %(off)s; background: transparent; padding: 14px 12px 3px 12px; }
QPushButton#quiet { background: transparent; border: 0; color: %(sub)s; text-align: left; padding: 4px 12px; }
QPushButton#quiet:hover { color: %(text)s; }
QPushButton#quiet:disabled { color: %(off)s; }
QPushButton#chip { border-radius: 15px; padding: 5px 16px 5px 12px; }
QFrame#hero { background: %(card)s; border: 1px solid %(line)s; border-radius: 12px; }
QLabel#headline { font-size: 20px; font-weight: 600; }
QFrame#card { background: %(card)s; border: 1px solid %(line)s; border-radius: 12px; }
QFrame#card:hover { border-color: %(accent)s; }
QLabel#cardvalue { font-size: 16px; font-weight: 600; }
QLabel#emptytitle { font-size: 18px; font-weight: 600; }
QFrame#activity { background: %(card)s; border: 1px solid %(line)s; border-radius: 8px; }
""" % c


def apply(accent=None):
    """Styles the whole application; call again when the vehicle (or its accent) changes."""
    app = QApplication.instance()
    accent = usable(accent)
    if app.property("dash_accent") == accent:
        return
    app.setProperty("dash_accent", accent)
    app.setStyle("Fusion")
    app.setPalette(palette(accent))
    app.setStyleSheet(sheet(accent))
