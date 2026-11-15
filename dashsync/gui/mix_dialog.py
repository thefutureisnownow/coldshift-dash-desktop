"""Mix and export: dashcam clips with engine and exhaust on two channels, made into a video with one mix of them.

The clips play in the window, joined end to end as they will be exported, with the mix as the sound: the balance
slider runs from only the left channel, through both at full level, to only the right, and each change is heard
a moment later (the mix is made again with ffmpeg, at the level export gives it). Until it is ready, and without
ffmpeg, the clips play with their sound as recorded.

Under the picture the trip log's revs, speed and throttle are drawn along the clips' time, to find the part
worth keeping; Start here and End here (or I and O) mark it, and only that part is exported. Space plays and
pauses. Export writes an .mp4 (several clips joined into one), by default
into an Exports folder beside the copied recordings, the picture copied as it is. The balance and level choice
are remembered.
"""
import glob
import os
import tempfile

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox,
                               QProgressBar, QPushButton, QSizePolicy, QSlider, QVBoxLayout)

from .. import drives, ffmpegtool, mixdown, paths, recordings, tripfiles
from . import forms, worker
from .timeline import Timeline, clock


def channel_names(dest):
    """(left, right) names from the newest sound recording's CSV (the names set on the phone's Sound page, kept
    per car); ("Left", "Right") without one."""
    if dest:
        csvs = sorted(glob.glob(os.path.join(dest, "sound", "*.csv")), reverse=True)
        for c in csvs:
            names = recordings.sound_channels(dest, os.path.splitext(os.path.basename(c))[0])
            if len(names) >= 2 and names[0] and names[1]:
                return names[0], names[1]
    return "Left", "Right"


def lengths(clips):
    """Each clip's length in seconds: ffprobe's, else its .srt's, else what the dashcam usually makes."""
    if mixdown.tool("ffprobe"):
        try:
            return mixdown.durations(clips)
        except mixdown.MixError:
            pass
    out = []
    for c in clips:
        n = tripfiles._length_s(os.path.splitext(c)[0] + ".srt", "clips")
        out.append(n or float(drives.CLIP_S))
    return out


class MixDialog(QDialog):
    def __init__(self, parent, clips, dest):
        super().__init__(parent)
        self.setWindowTitle("Mix and export")
        self.dest = dest
        self.clips, self.durs, self.offsets, self.total = [], [], [], 0.0
        self.busy = False
        self.cur = -1                   # the clip in the player
        self.pending = None             # where to go (ms) once that clip has loaded
        self.playing = False
        self.raw_wav = None             # the clips' sound as recorded, read out once, that each mix is made from
        self.raw_for = None
        self.mix_wav = None             # the mix the player plays beside the picture
        self.mix_for = None             # (clips, balance, level) it was made for
        self.mix_job = 0
        self.trim = [None, None]
        cfg = paths.load_config()
        left, right = channel_names(dest)
        self.left_name, self.right_name = left, right

        # the player: the picture (and its own sound until the mix is ready), and the mix
        self.video = QVideoWidget()
        self.video.setMinimumHeight(240)
        self.video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.player = QMediaPlayer(self)
        self.own_sound = QAudioOutput(self)
        self.player.setAudioOutput(self.own_sound)
        self.player.setVideoOutput(self.video)
        self.player.mediaStatusChanged.connect(self._status)
        self.player.errorOccurred.connect(lambda _e, msg: self.note.setText("The player can't show this clip: " + msg))
        self.mixer = QMediaPlayer(self)
        self.mix_out = QAudioOutput(self)
        self.mixer.setAudioOutput(self.mix_out)
        self.tick = QTimer(self)
        self.tick.setInterval(100)
        self.tick.timeout.connect(self._tick)
        self.tick.start()

        self.play_btn = QPushButton("Play")
        self.play_btn.setToolTip("Play or pause (Space)")
        self.play_btn.clicked.connect(self.toggle)
        self.time_label = QLabel("0:00 / 0:00")
        self.sound_label = forms.note("")
        prow = QHBoxLayout()
        prow.addWidget(self.play_btn)
        prow.addWidget(self.time_label)
        prow.addStretch()
        prow.addWidget(self.sound_label)

        self.timeline = Timeline()
        self.timeline.seek.connect(self.seek)

        self.in_btn = QPushButton("Start here")
        self.in_btn.setToolTip("The export starts where the video is now (I)")
        self.in_btn.clicked.connect(lambda: self.set_trim(0))
        self.out_btn = QPushButton("End here")
        self.out_btn.setToolTip("The export ends where the video is now (O)")
        self.out_btn.clicked.connect(lambda: self.set_trim(1))
        self.clear_btn = QPushButton("All of it")
        self.clear_btn.clicked.connect(self.clear_trim)
        self.trim_label = QLabel()
        trow = QHBoxLayout()
        for w in (self.in_btn, self.out_btn, self.clear_btn):
            trow.addWidget(w)
        trow.addWidget(self.trim_label, 1)

        self.list = QListWidget()
        self.list.setMaximumHeight(76)
        self.list.itemDoubleClicked.connect(lambda it: self.seek(self.offsets[self.list.row(it)] + 0.01))
        self.list.setToolTip("Double-click to go to that clip")
        add = QPushButton("Add clips…")
        add.clicked.connect(self.add_clips)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_clips)
        side = QVBoxLayout()
        side.addWidget(add)
        side.addWidget(remove)
        side.addStretch()
        lrow = QHBoxLayout()
        lrow.addWidget(self.list, 1)
        lrow.addLayout(side)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(-100, 100)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(50)
        self.slider.setValue(int(cfg.get("mix_balance", 0)))
        self.slider.valueChanged.connect(self._balance_changed)
        brow = QHBoxLayout()
        brow.addWidget(QLabel(left))
        brow.addWidget(self.slider, 1)
        brow.addWidget(QLabel(right))
        self.balance_label = QLabel()
        centre = QPushButton("Both full")
        centre.clicked.connect(lambda: self.slider.setValue(0))
        crow = QHBoxLayout()
        crow.addWidget(QLabel("Balance: %s (left) and %s (right), mixed into one and put on both channels" % (left, right)))
        crow.addStretch()
        crow.addWidget(self.balance_label)
        crow.addWidget(centre)
        self.remix = QTimer(self)
        self.remix.setSingleShot(True)
        self.remix.setInterval(500)
        self.remix.timeout.connect(self.make_mix)

        self.normalize = QCheckBox("Level for YouTube (−14 LUFS, the loudest peak kept under −1 dB)")
        self.normalize.setChecked(bool(cfg.get("mix_normalize", True)))
        self.normalize.toggled.connect(lambda *_: self.remix.start())
        self.join = QCheckBox("Join the clips into one video")
        self.join.setChecked(True)
        self.join.toggled.connect(lambda *_: self._buttons())
        orow = QHBoxLayout()
        orow.addWidget(self.normalize)
        orow.addStretch()
        orow.addWidget(self.join)

        self.export_btn = QPushButton("Export…")
        self.export_btn.setDefault(True)
        self.export_btn.clicked.connect(self.export)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(forms.note("The picture is copied as it is; only the sound is made again."), 1)
        buttons.addWidget(self.export_btn)
        buttons.addWidget(close)

        self.bar = QProgressBar()
        self.bar.hide()
        self.note = QLabel()
        self.note.setWordWrap(True)

        # ffmpeg, the way the Phone page offers adb: download it, or point at a copy
        self.ff_label = QLabel()
        self.ff_label.setWordWrap(True)
        self.ff_download = QPushButton("Download ffmpeg…")
        self.ff_download.clicked.connect(self.download_ffmpeg)
        self.ff_choose = QPushButton("Choose ffmpeg…")
        self.ff_choose.clicked.connect(self.choose_ffmpeg)
        frow = QHBoxLayout()
        frow.addWidget(self.ff_label, 1)
        frow.addWidget(self.ff_download)
        frow.addWidget(self.ff_choose)

        page = QVBoxLayout(self)
        page.addLayout(frow)
        page.addWidget(self.video, 1)
        page.addLayout(prow)
        page.addWidget(self.timeline)
        page.addLayout(trow)
        page.addLayout(lrow)
        page.addLayout(crow)
        page.addLayout(brow)
        page.addLayout(orow)
        page.addWidget(self.bar)
        page.addWidget(self.note)
        page.addLayout(buttons)
        self.resize(980, 860)

        for keys, fn in (("Space", self.toggle), ("I", lambda: self.set_trim(0)), ("O", lambda: self.set_trim(1))):
            QShortcut(QKeySequence(keys), self, fn)

        self.show_ffmpeg(ffmpegtool.status(), remix=False)
        self._balance_text()
        self.set_clips(clips)

    # ---- ffmpeg ----

    def show_ffmpeg(self, st, remix=True):
        self.have_ffmpeg = st["found"]
        self.ff_label.setText("" if st["found"] else "Mixing needs ffmpeg, which isn't installed. " + st["hint"])
        for w in (self.ff_label, self.ff_download, self.ff_choose):
            w.setVisible(not st["found"])
        self._buttons()
        if remix:
            self.read_sound()

    def download_ffmpeg(self):
        ans = QMessageBox.question(
            self, "Download ffmpeg",
            "ffmpeg is free software (GPL). The tool downloads a ready-built copy of ffmpeg and ffprobe from the builds "
            "listed on %s, checks them against the published checksums, and keeps them in its own folder.\n\n"
            "Download them now?"
            % ffmpegtool.SOURCE_PAGE)
        if ans != QMessageBox.Yes:
            return
        self._begin("Downloading ffmpeg…")
        self.bar.setRange(0, 1000)
        worker.run(lambda report: ffmpegtool.setup(progress=report), self._ffmpeg_installed, self._failed,
                   progress=self._download_progress)

    def _download_progress(self, done, total):
        if total:
            self.bar.setValue(int(done * 1000 / total))
        self.note.setText("Downloading ffmpeg: %.0f MB" % (done / 1e6))

    def _ffmpeg_installed(self, result):
        self._end()
        self.note.setText("ffmpeg %s is installed." % result[1])
        self.show_ffmpeg(ffmpegtool.status())

    def choose_ffmpeg(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose ffmpeg (ffprobe must be in the same folder)")
        if not path:
            return
        try:
            ffmpegtool.set_path(path)
        except ValueError as e:
            forms.error(self, "Choosing ffmpeg", str(e))
            return
        self.show_ffmpeg(ffmpegtool.status())

    # ---- the clips ----

    def set_clips(self, clips):
        self.clips = sorted(dict.fromkeys(clips), key=lambda p: os.path.basename(p))
        self.list.clear()
        self.list.addItems([os.path.basename(p) for p in self.clips])
        self.pause()
        self.player.setSource(QUrl())
        self.cur = -1
        self.durs, self.offsets, self.total = [], [], 0.0
        self.trim = [None, None]
        self._drop_raw()
        self.mix_job += 1                           # a mix of the old list is thrown away when it comes
        self.mixer.stop()
        self.mixer.setSource(QUrl())
        if self.mix_wav:
            _remove(self.mix_wav)
        self.mix_wav = self.mix_for = None
        self.own_sound.setMuted(False)              # the clips' own sound until the new mix is ready
        self.timeline.set_clips(0, [], [])
        self.timeline.set_trim(None, None)
        self._trim_text()
        self._buttons()
        if not self.clips:
            self.sound_label.setText("")
            return
        clips, dest = list(self.clips), self.dest
        self.note.setText("Reading the clips…")

        def work():
            durs = lengths(clips)
            total, bounds, samples = drives.joined(clips, dest, durs)
            return clips, durs, total, bounds, samples
        worker.run(work, self._read, self._failed)

    def _read(self, result):
        clips, durs, total, bounds, samples = result
        if clips != self.clips:
            return                              # the list changed since
        self.durs, self.total = durs, total
        self.offsets = [0.0] + bounds
        self.timeline.set_clips(total, bounds, samples)
        self.note.setText("")
        self._load(0, 0)
        self._buttons()
        self.read_sound()

    def read_sound(self):
        """Reads the clips' sound out once, then makes the mix from it."""
        if not self.clips or not self.durs or not getattr(self, "have_ffmpeg", False):
            self._sound_text()
            return
        if self.raw_for == tuple(self.clips) and self.raw_wav:
            self.make_mix()
            return
        clips = list(self.clips)
        fd, raw = tempfile.mkstemp(prefix="coldshift-sound-", suffix=".wav")
        os.close(fd)
        self.mix_job += 1
        job = self.mix_job
        self._sound_text(making=True)
        worker.run(lambda: mixdown.extract(clips, raw), lambda _r: self._sound_read(job, clips, raw),
                   lambda msg: self._mix_failed(job, raw, msg))

    def _sound_read(self, job, clips, raw):
        if job != self.mix_job or clips != self.clips:
            _remove(raw)
            return
        self._drop_raw()
        self.raw_wav, self.raw_for = raw, tuple(clips)
        self.make_mix()

    def _drop_raw(self):
        if self.raw_wav:
            _remove(self.raw_wav)
        self.raw_wav = self.raw_for = None

    def add_clips(self):
        start = os.path.join(self.dest, "clips") if self.dest else ""
        files, _ = QFileDialog.getOpenFileNames(self, "Add dashcam clips", start, "Videos (*.mp4)")
        if files:
            self.set_clips(self.clips + files)

    def remove_clips(self):
        gone = {self.clips[i.row()] for i in self.list.selectedIndexes()}
        self.set_clips([c for c in self.clips if c not in gone])

    def _buttons(self):
        ready = bool(self.clips) and bool(self.durs) and not self.busy
        self.export_btn.setEnabled(ready and getattr(self, "have_ffmpeg", False))
        self.play_btn.setEnabled(ready)
        self.join.setVisible(len(self.clips) > 1)
        trimming = ready and (len(self.clips) == 1 or self.join.isChecked())
        for b in (self.in_btn, self.out_btn, self.clear_btn):
            b.setEnabled(trimming)

    # ---- the player ----

    def position(self):
        """Seconds into the joined clips."""
        if self.cur < 0:
            return 0.0
        ms = self.pending if self.pending is not None else self.player.position()
        return self.offsets[self.cur] + ms / 1000.0

    def _clip_at(self, s):
        for i in range(len(self.offsets) - 1, -1, -1):
            if s >= self.offsets[i]:
                return i
        return 0

    def _load(self, i, ms):
        """Shows clip i from `ms` in."""
        if i == self.cur:
            self.player.setPosition(int(ms))
            return
        self.cur, self.pending = i, int(ms)
        self.player.stop()              # (a player still "playing" the last file ignores play() on the next)
        self.player.setSource(QUrl.fromLocalFile(self.clips[i]))

    def _status(self, status):
        mine = 0 <= self.cur < len(self.clips) and self.player.source() == QUrl.fromLocalFile(self.clips[self.cur])
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and self.pending is not None and mine:
            self.player.setPosition(self.pending)
            self.pending = None
            if self.playing:
                self.player.play()
                self._sync(force=True)
        elif status == QMediaPlayer.EndOfMedia:
            # (changing the player's file from inside its own signal leaves it stuck: after it returns)
            if self.cur + 1 < len(self.clips):
                QTimer.singleShot(0, lambda: self._load(self.cur + 1, 0))
            else:
                QTimer.singleShot(0, lambda: (self.pause(), self.seek(0)))

    def seek(self, s):
        if not self.clips or not self.durs:
            return
        s = max(0.0, min(self.total - 0.05, s))
        i = self._clip_at(s)
        self._load(i, (s - self.offsets[i]) * 1000)
        if self.mix_wav:
            self.mixer.setPosition(int(s * 1000))
        self.timeline.set_pos(s)
        self._show_time(s)

    def toggle(self):
        self.pause() if self.playing else self.play()

    def play(self):
        if not self.durs:
            return
        self.playing = True
        self.play_btn.setText("Pause")
        if self.pending is None:
            self.player.play()
        if self.mix_wav:
            self._sync(force=True)
            self.mixer.play()

    def pause(self):
        self.playing = False
        self.play_btn.setText("Play")
        self.player.pause()
        self.mixer.pause()

    def _sync(self, force=False):
        """Keeps the mix with the picture: it plays on its own, and is moved back in line when it drifts."""
        if not self.mix_wav:
            return
        want = int(self.position() * 1000)
        if force or abs(self.mixer.position() - want) > 150:
            self.mixer.setPosition(want)

    def _tick(self):
        if not self.durs:
            return
        s = self.position()
        self.timeline.set_pos(s)
        self._show_time(s)
        if self.playing and self.mix_wav:
            loading = self.pending is not None
            if loading and self.mixer.playbackState() == QMediaPlayer.PlayingState:
                self.mixer.pause()                  # the next clip is loading: wait for it
            elif not loading:
                if self.mixer.playbackState() != QMediaPlayer.PlayingState:
                    self._sync(force=True)
                    self.mixer.play()
                else:
                    self._sync()

    def _show_time(self, s):
        self.time_label.setText("%s / %s" % (clock(s), clock(self.total)))

    # ---- the mix, heard ----

    def _balance_changed(self, *_):
        self._balance_text()
        self.remix.start()

    def make_mix(self):
        """Makes the mix the player plays (again, after a change), in the background."""
        if not self.clips or not self.durs or not getattr(self, "have_ffmpeg", False):
            self._sound_text()
            return
        if self.raw_for != tuple(self.clips) or not self.raw_wav:
            return                                  # read_sound makes it once the sound is read
        want = (tuple(self.clips), self.slider.value(), self.normalize.isChecked())
        if want == self.mix_for:
            return
        self.mix_job += 1
        job, clips, b, norm, raw = self.mix_job, list(self.clips), self.balance(), self.normalize.isChecked(), self.raw_wav
        fd, wav = tempfile.mkstemp(prefix="coldshift-mix-", suffix=".wav")
        os.close(fd)
        self._sound_text(making=True)
        worker.run(lambda: (mixdown.render(clips, wav, b, norm, source=raw), wav),
                   lambda r: self._mixed(job, want, r[1]),
                   lambda msg: self._mix_failed(job, wav, msg))

    def _mixed(self, job, want, wav):
        if job != self.mix_job:
            _remove(wav)                            # a newer one is on its way
            return
        old, self.mix_wav, self.mix_for = self.mix_wav, wav, want
        self.mixer.setSource(QUrl.fromLocalFile(wav))
        self.own_sound.setMuted(True)
        self._sync(force=True)
        if self.playing and self.pending is None:
            self.mixer.play()
        if old:
            QTimer.singleShot(500, lambda: _remove(old))
        self._sound_text()

    def _mix_failed(self, job, wav, msg):
        _remove(wav)
        if job == self.mix_job:
            self._sound_text()
            self.note.setText("The mix couldn't be made to listen to: %s" % msg)

    def _sound_text(self, making=False):
        if not getattr(self, "have_ffmpeg", False):
            text = "Sound: as recorded (mixing needs ffmpeg)"
        elif making:
            text = "Sound: as recorded, while the mix is made…" if not self.mix_wav else "Sound: making the new mix…"
        elif self.mix_wav:
            text = "Sound: your mix"
        else:
            text = ""
        self.sound_label.setText(text)

    # ---- the part to export ----

    def set_trim(self, end):
        if not self.in_btn.isEnabled():
            return
        s = round(self.position(), 1)
        self.trim[end] = s
        a, b = self.trim
        if a is not None and b is not None and b - a < 1:
            self.trim[1 - end] = None               # the other end was on the wrong side: start again from here
        self.timeline.set_trim(*self.trim)
        self._trim_text()

    def clear_trim(self):
        self.trim = [None, None]
        self.timeline.set_trim(None, None)
        self._trim_text()

    def _trim_text(self):
        a, b = self.trim
        if a is None and b is None:
            self.trim_label.setText("Exports all of it" + (" (%s)" % clock(self.total) if self.total else ""))
        else:
            a, b = a or 0.0, b if b is not None else self.total
            self.trim_label.setText("Exports %s to %s (%s)" % (clock(a), clock(b), clock(b - a)))

    # ---- balance ----

    def balance(self):
        return self.slider.value() / 100.0

    def _balance_text(self, *_):
        gl, gr = mixdown.gains(self.balance())
        self.balance_label.setText("%s %d%%  ·  %s %d%%" % (self.left_name, round(gl * 100), self.right_name, round(gr * 100)))

    def _remember(self):
        cfg = paths.load_config()
        cfg["mix_balance"] = self.slider.value()
        cfg["mix_normalize"] = self.normalize.isChecked()
        paths.save_config(cfg)

    # ---- export ----

    def export(self):
        if not self.clips:
            return
        self._remember()
        self.pause()
        joined = self.join.isChecked() or len(self.clips) == 1
        groups = [self.clips] if joined else [[c] for c in self.clips]
        start, end = (self.trim if joined else (None, None))
        folder = os.path.join(self.dest, "Exports") if self.dest else os.path.dirname(self.clips[0])
        if len(groups) == 1:
            name = mixdown.default_name(groups[0])
            if start is not None or end is not None:
                name = name[:-4] + " %s-%s.mp4" % (clock(start or 0).replace(":", "."),
                                                   clock(end if end is not None else self.total).replace(":", "."))
            out, _ = QFileDialog.getSaveFileName(self, "Export the video", os.path.join(folder, name), "Videos (*.mp4)")
            if not out:
                return
            if not out.lower().endswith(".mp4"):
                out += ".mp4"
            jobs = [(groups[0], out)]
        else:
            folder = QFileDialog.getExistingDirectory(self, "Export the videos into", folder)
            if not folder:
                return
            jobs = [(g, os.path.join(folder, mixdown.default_name(g))) for g in groups]
        b, norm = self.balance(), self.normalize.isChecked()
        self._begin("Exporting…")
        self.bar.setRange(0, 1000)

        def work(report):
            done = []
            for n, (clips, out) in enumerate(jobs):
                done.append(mixdown.export(clips, out, b, norm, start=start, end=end,
                                           progress=lambda d, t, n=n: report((n, len(jobs), d, t, out), None)))
            return done
        worker.run(work, self._exported, self._failed, progress=self._progress)

    def _progress(self, info, _):
        n, count, done, total, out = info
        self.bar.setValue(int(1000 * (n + (done / total if total else 1)) / count))
        self.note.setText("Exporting %s%s: %d of %d s" % (os.path.basename(out),
                                                       " (%d of %d)" % (n + 1, count) if count > 1 else "", done, total))

    def _exported(self, results):
        self._end()
        last = results[-1]
        level = ("level %+.1f dB" % last["gain_db"]) if last["loudness"] is not None else "silent"
        self.note.setText("Exported %s (%s)." % (", ".join(os.path.basename(r["out"]) for r in results), level))
        forms.reveal(last["out"])

    # ---- shared ----

    def _begin(self, text):
        self.busy = True
        self.bar.setRange(0, 0)
        self.bar.show()
        self.note.setText(text)
        self._buttons()

    def _end(self):
        self.busy = False
        self.bar.hide()
        self._buttons()

    def _failed(self, msg):
        self._end()
        self.note.setText("")
        forms.error(self, "Mixing", msg)

    def done(self, r):
        self.tick.stop()
        self.remix.stop()
        self.mix_job += 1                           # a mix still being made is thrown away when it comes
        self.player.stop()
        self.mixer.stop()
        self.mixer.setSource(QUrl())
        if self.mix_wav:
            _remove(self.mix_wav)
            self.mix_wav = None
        self._drop_raw()
        super().done(r)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
