"""Small pictures for the Recordings list, made in the background as they are asked for.

dashsync.thumbs makes them with ffmpeg (or Pillow for photos), a few at a time in a pool of their own so the
phone's jobs never wait behind them. Without ffmpeg a video's still is grabbed with Qt's player instead, one at a
time. Either way it is kept in the cache, so it is made once.
"""
import os

from PySide6.QtCore import QObject, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QIcon, QPixmap

from .. import thumbs
from . import worker


class Thumbs(QObject):
    ready = Signal(str)             # the source file whose picture is now there

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.asked = set()          # sources already asked for (made, being made, or that failed)
        self.jobs = set()
        self.grab_queue = []
        self.grabber = None

    def icon(self, src):
        p = thumbs.cached(src)
        return QIcon(QPixmap(p)) if p else None

    def want(self, srcs):
        """Makes the pictures of `srcs` there aren't yet; `ready` says as each comes."""
        for src in srcs:
            if src in self.asked or thumbs.cached(src):
                continue
            self.asked.add(src)
            if thumbs.can_make(src):
                job = worker.Job(lambda src=src: thumbs.make(src))
                self.jobs.add(job.signals)
                job.signals.done.connect(lambda p, src=src, s=job.signals: self._made(src, p, s))
                job.signals.failed.connect(lambda _m, s=job.signals: self.jobs.discard(s))
                job.setAutoDelete(True)
                self.pool.start(job)
            elif src.lower().endswith(thumbs.VIDEO):
                self.grab_queue.append(src)
        self._grab_next()

    def _made(self, src, path, signals):
        self.jobs.discard(signals)
        if path:
            self.ready.emit(src)

    # ---- without ffmpeg: Qt's player ----

    def _grab_next(self):
        if self.grabber or not self.grab_queue:
            return
        src = self.grab_queue.pop(0)
        self.grabber = _Grab(src, self)
        self.grabber.finished.connect(self._grabbed)

    def _grabbed(self, src, ok):
        self.grabber.deleteLater()
        self.grabber = None
        if ok:
            self.ready.emit(src)
        QTimer.singleShot(0, self._grab_next)


class _Grab(QObject):
    """One still from a video, 1 s in, with Qt's player (no sound, nothing shown)."""
    finished = Signal(str, bool)

    def __init__(self, src, parent):
        super().__init__(parent)
        from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
        self.src, self.done = src, False
        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._frame)
        self.player.errorOccurred.connect(lambda *_: self._finish(False))
        QTimer.singleShot(8000, lambda: self._finish(False))
        self.player.setSource(QUrl.fromLocalFile(src))
        self.player.setPosition(1000)
        self.player.play()

    def _frame(self, frame):
        if self.done or not frame.isValid() or self.player.position() < 900:
            return
        img = frame.toImage()
        if img.isNull():
            return
        small = img.scaledToWidth(thumbs.WIDTH)
        try:
            thumbs.save(self.src, lambda path: small.save(path, "JPEG", 85))
            self._finish(True)
        except OSError:
            self._finish(False)

    def _finish(self, ok):
        if self.done:
            return
        self.done = True
        self.player.stop()
        self.finished.emit(self.src, ok and os.path.isfile(thumbs.cached(self.src) or ""))
