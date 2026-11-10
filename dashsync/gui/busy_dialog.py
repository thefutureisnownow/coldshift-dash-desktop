"""The window over the window while a sync runs: what is running, how far it is, and Cancel. It keeps
the rest of the application out of reach until the job is done, so nothing is changed under a copy.

A job of several parts (the Overview's sync) lists them, ticked off as they finish, with the running
part's own progress and what it is doing under the list. Any other job shows its progress (State.span,
State.value) and repeats the page's words for it (State.watch). A look at the phone ("checking…", "looking…") is quick and changes nothing, so it does not get one."""
import html

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from . import forms, theme, worker


class BusyDialog(QDialog):
    def __init__(self, parent, state):
        super().__init__(parent)
        self.state = state
        self.setWindowModality(Qt.WindowModal)
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)     # no close button
        self.setWindowTitle("coldshift.dash")
        self.title = QLabel()
        self.title.setObjectName("headline")
        self.steps = QLabel()                   # the parts of the job, one a line
        self.steps.setTextFormat(Qt.RichText)
        self.steps.hide()
        self.listed = None                      # what self.steps shows: (the steps, the one running)
        self.detail = forms.note("")
        self.detail.setMinimumHeight(36)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setAutoDefault(False)           # stopping is not the main thing to do here
        self.cancel_btn.clicked.connect(self.cancel)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.cancel_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(12)
        lay.addWidget(self.title)
        lay.addWidget(self.steps)
        lay.addWidget(self.bar)
        lay.addWidget(self.detail)
        lay.addLayout(row)
        self.setFixedWidth(520)
        self.stopping = False
        # a job that is over at once (a few small files) never shows the dialog
        self.wait = QTimer(self)
        self.wait.setSingleShot(True)
        self.wait.setInterval(400)
        self.wait.timeout.connect(self._open)
        self.tick = QTimer(self)
        self.tick.setInterval(120)
        self.tick.timeout.connect(self._repeat)
        state.busy_changed.connect(self._busy_changed)

    def _busy_changed(self):
        busy = self.state.busy
        if busy and not self.state.quiet():
            self.stopping = False
            self.wait.start()
        else:
            self.wait.stop()
            self.tick.stop()
            self.hide()

    def _open(self):
        if not self.state.busy:
            return
        self._repeat()
        self.tick.start()
        self.show()

    def _repeat(self):
        busy = self.state.busy
        if not busy:
            return
        note = self.state.note
        self.title.setText("Stopping…" if self.stopping else busy[0].upper() + busy[1:] + "…")
        self.bar.setRange(*self.state.span)
        self.bar.setValue(self.state.value)
        steps, at = self.state.steps, self.state.step
        if (steps, at) != self.listed:
            self.listed = (list(steps), at)
            self.steps.setText(self._list(steps, at))
            self.steps.setVisible(bool(steps))
            self.adjustSize()
        try:
            text = self.state.detail if steps else note.text() if note is not None else ""
        except RuntimeError:                # the page went away (the vehicle was switched)
            text = ""
        self.detail.setText("It stops once the file being copied is done." if self.stopping else text)
        can = worker.can_cancel()
        self.cancel_btn.setEnabled(can and not self.stopping)
        self.cancel_btn.setToolTip("" if can else "This step is short and cannot be stopped part-way")

    @staticmethod
    def _list(steps, at):
        """The steps as lines: a tick for each one done, the running one in bold, the rest greyed."""
        accent = QApplication.instance().property("dash_accent") or theme.ACCENT
        lines = []
        for i, name in enumerate(steps):
            name = html.escape(name)
            if i < at:
                lines.append("<span style='color:%s'>✓</span>&nbsp;&nbsp;<span style='color:%s'>%s</span>"
                             % (theme.GOOD, theme.SUB, name))
            elif i == at:
                lines.append("<span style='color:%s'>●</span>&nbsp;&nbsp;<b>%s</b>" % (accent, name))
            else:
                lines.append("<span style='color:%s'>○&nbsp;&nbsp;%s</span>" % (theme.OFF, name))
        return "<div style='line-height:150%%'>%s</div>" % "<br>".join(lines)

    def cancel(self):
        if worker.can_cancel() and not self.stopping:
            self.stopping = True
            worker.cancel()
            self._repeat()

    def reject(self):
        """Esc asks to cancel; the dialog only goes when the job has stopped."""
        self.cancel()

    def closeEvent(self, e):
        if self.state.busy:
            e.ignore()
            self.cancel()
        else:
            e.accept()
