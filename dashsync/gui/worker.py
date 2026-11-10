"""Runs tool functions off the UI thread and reports back through Qt signals.

The library raises SystemExit for messages meant for the user (the CLI prints them), so those are
reported as failures with their text, like any other exception.

A job that reports progress can be cancelled: `cancel()` makes its next progress report raise, so it
stops between files (copies land as *.part and are renamed when whole, and downloads resume). It then
fails with the text CANCELLED, which forms.error does not show as an error.
"""
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


CANCELLED = "cancelled"


class _Signals(QObject):
    progress = Signal(object, object)
    done = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, fn, with_progress=False):
        super().__init__()
        self.fn, self.with_progress = fn, with_progress
        self.cancelled = False
        self.signals = _Signals()

    def _emit(self, signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:
            pass                # the window closed while this ran: nobody is left to tell

    def _report(self, done, total):
        if self.cancelled:
            raise SystemExit(CANCELLED)
        self._emit(self.signals.progress, done, total)

    def run(self):
        try:
            if self.with_progress:
                result = self.fn(self._report)
            else:
                result = self.fn()
        except SystemExit as e:
            self._emit(self.signals.failed, str(e.code) if e.code is not None else "stopped")
        except Exception as e:
            traceback.print_exc()
            self._emit(self.signals.failed, str(e) or e.__class__.__name__)
        else:
            self._emit(self.signals.done, result)


_alive = set()
_stoppable = set()          # running jobs that report progress


def can_cancel():
    return bool(_stoppable)


def cancel():
    """Asks every running job that reports progress to stop at its next report."""
    for job in _stoppable:
        job.cancelled = True


def run(fn, done=None, failed=None, progress=None):
    """Starts fn() in the pool. With `progress`, fn is called as fn(report) and report(done, total)
    reaches `progress` on the UI thread."""
    job = Job(fn, with_progress=progress is not None)
    _alive.add(job.signals)      # keep the signal object alive until the job reports
    if done:
        job.signals.done.connect(done)
    if failed:
        job.signals.failed.connect(failed)
    if progress:
        job.signals.progress.connect(progress)
    job.signals.done.connect(lambda *_: (_alive.discard(job.signals), _stoppable.discard(job)))
    job.signals.failed.connect(lambda *_: (_alive.discard(job.signals), _stoppable.discard(job)))
    if progress:
        _stoppable.add(job)
    QThreadPool.globalInstance().start(job)
    return job
