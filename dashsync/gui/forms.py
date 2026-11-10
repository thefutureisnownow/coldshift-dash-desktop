"""Small things the pages share: forms that use the page's width, muted notes that work in dark mode,
one way to show errors, and the platform's words for showing a folder."""
import os
import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPalette
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from .worker import CANCELLED

SHOW_FOLDER = "Show in Finder" if sys.platform == "darwin" else "Show in Explorer" if os.name == "nt" else "Open folder"
# a red readable on light and dark backgrounds (about 4.5:1 on both)
WARN = "#d9534f"


def form(parent=None):
    """A label/value form that uses the page's width. On macOS a QFormLayout defaults to centred rows
    whose fields keep their natural width, which cuts wrapped text off."""
    f = QFormLayout(parent) if parent is not None else QFormLayout()
    f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    f.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    f.setLabelAlignment(Qt.AlignLeft)
    f.setRowWrapPolicy(QFormLayout.DontWrapRows)
    return f


def muted(label):
    """Greys a label the way the platform greys secondary text (dark mode included)."""
    pal = label.palette()
    pal.setColor(QPalette.WindowText, pal.color(QPalette.PlaceholderText))
    label.setPalette(pal)
    return label


def note(text):
    lab = QLabel(text)
    lab.setWordWrap(True)
    return muted(lab)


def empty(title, text, *buttons):
    """What a page shows in place of an empty list: what is missing, how it gets here, and the buttons that
    bring it. Returns (widget, the text label) so the page can change the words."""
    head = QLabel(title)
    head.setObjectName("emptytitle")
    head.setAlignment(Qt.AlignCenter)
    words = note(text)
    words.setAlignment(Qt.AlignCenter)
    words.setFixedWidth(460)
    mid = QHBoxLayout()              # centred by stretches: an alignment flag would cut a wrapped label short
    mid.addStretch()
    mid.addWidget(words)
    mid.addStretch()
    row = QHBoxLayout()
    row.addStretch()
    for b in buttons:
        row.addWidget(b)
    row.addStretch()
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setSpacing(10)
    lay.addStretch(2)
    lay.addWidget(head)
    lay.addLayout(mid)
    lay.addLayout(row)
    lay.addStretch(3)
    return w, words


def show_folder(path):
    os.makedirs(path, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def error(parent, action, msg):
    """One way to say something failed: titled by what was being done, in a sentence, with the Phone
    page's advice for the usual adb states. A job the user cancelled is not a failure: nothing is shown."""
    msg = (msg or "it stopped").strip()
    if msg == CANCELLED:
        return
    low = msg.lower()
    if "unauthorized" in low:
        msg += "\n\nUnlock the phone and accept the “Allow USB debugging?” prompt, then try again."
    elif "offline" in low or "device not found" in low or "no devices" in low:
        msg += "\n\nThe phone is not connected: check the cable (or Wi-Fi), then press Refresh on the Phone page."
    msg = msg[0].upper() + msg[1:]
    if msg[-1] not in ".!?\n":
        msg += "."
    QMessageBox.warning(parent, action + " failed" if action else "coldshift.dash", msg)
