"""Mix and export: dashcam clips with engine and exhaust on two channels, made into a video with one mix of them.

The balance slider runs from only the left channel, through both at full level, to only the right. Preview plays
20 s of the first clip as it will sound. Export writes an .mp4 (several clips joined into one, in time order),
by default into an Exports folder beside the copied recordings. The balance and level choice are remembered.
"""
import glob
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox,
                               QProgressBar, QPushButton, QSlider, QVBoxLayout)

from .. import ffmpegtool, mixdown, paths, recordings
from . import forms, sound, worker


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


class MixDialog(QDialog):
    def __init__(self, parent, clips, dest):
        super().__init__(parent)
        self.setWindowTitle("Mix and export")
        self.dest = dest
        self.clips = []
        self.preview_wav = None
        self.busy = False
        cfg = paths.load_config()
        left, right = channel_names(dest)
        self.left_name, self.right_name = left, right

        self.list = QListWidget()
        add = QPushButton("Add clips…")
        add.clicked.connect(self.add_clips)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_clips)
        lrow = QHBoxLayout()
        lrow.addWidget(add)
        lrow.addWidget(remove)
        lrow.addStretch()

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(-100, 100)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(50)
        self.slider.setValue(int(cfg.get("mix_balance", 0)))
        self.slider.valueChanged.connect(self._balance_text)
        brow = QHBoxLayout()
        brow.addWidget(QLabel(left))
        brow.addWidget(self.slider, 1)
        brow.addWidget(QLabel(right))
        self.balance_label = QLabel()
        centre = QPushButton("Both full")
        centre.clicked.connect(lambda: self.slider.setValue(0))
        crow = QHBoxLayout()
        crow.addWidget(self.balance_label, 1)
        crow.addWidget(centre)

        self.normalize = QCheckBox("Level for YouTube (−14 LUFS, the loudest peak kept under −1 dB)")
        self.normalize.setChecked(bool(cfg.get("mix_normalize", True)))
        self.join = QCheckBox("Join the clips into one video")
        self.join.setChecked(True)

        self.preview_btn = QPushButton("Preview 20 s")
        self.preview_btn.clicked.connect(self.preview)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(sound.stop)
        self.export_btn = QPushButton("Export…")
        self.export_btn.setDefault(True)
        self.export_btn.clicked.connect(self.export)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        for w in (self.preview_btn, self.stop_btn):
            buttons.addWidget(w)
        buttons.addStretch()
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
        page.addWidget(QLabel("Clips"))
        page.addWidget(self.list, 1)
        page.addLayout(lrow)
        page.addWidget(QLabel("Balance: %s (left) and %s (right), mixed into one and put on both channels" % (left, right)))
        page.addLayout(brow)
        page.addLayout(crow)
        page.addWidget(self.normalize)
        page.addWidget(self.join)
        page.addWidget(forms.note("The picture is copied as it is; only the sound is made again."))
        page.addLayout(buttons)
        page.addWidget(self.bar)
        page.addWidget(self.note)
        self.resize(640, 520)

        self.set_clips(clips)
        self._balance_text()
        self.show_ffmpeg(ffmpegtool.status())

    # ---- ffmpeg ----

    def show_ffmpeg(self, st):
        self.have_ffmpeg = st["found"]
        self.ff_label.setText("" if st["found"] else "Mixing needs ffmpeg, which isn't installed. " + st["hint"])
        for w in (self.ff_label, self.ff_download, self.ff_choose):
            w.setVisible(not st["found"])
        self._buttons()

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
        self._buttons()

    def add_clips(self):
        start = os.path.join(self.dest, "clips") if self.dest else ""
        files, _ = QFileDialog.getOpenFileNames(self, "Add dashcam clips", start, "Videos (*.mp4)")
        if files:
            self.set_clips(self.clips + files)

    def remove_clips(self):
        gone = {self.clips[i.row()] for i in self.list.selectedIndexes()}
        self.set_clips([c for c in self.clips if c not in gone])

    def _buttons(self):
        have = bool(self.clips) and not self.busy and getattr(self, "have_ffmpeg", False)
        self.preview_btn.setEnabled(have)
        self.export_btn.setEnabled(have)
        self.join.setVisible(len(self.clips) > 1)

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

    # ---- preview ----

    def preview(self):
        if not self.clips:
            return
        self._remember()
        self._begin("Making a preview of %s…" % os.path.basename(self.clips[0]))
        clip, b, norm = self.clips[0], self.balance(), self.normalize.isChecked()
        worker.run(lambda: mixdown.preview(clip, b, norm), self._previewed, self._failed)

    def _previewed(self, wav):
        self._end()
        self._drop_preview()
        self.preview_wav = wav
        self.note.setText("Playing the first 20 s of %s." % os.path.basename(self.clips[0]))
        sound.play(wav)

    def _drop_preview(self):
        if self.preview_wav:
            sound.stop()
            try:
                os.remove(self.preview_wav)
            except OSError:
                pass
            self.preview_wav = None

    # ---- export ----

    def export(self):
        if not self.clips:
            return
        self._remember()
        groups = [self.clips] if (self.join.isChecked() or len(self.clips) == 1) else [[c] for c in self.clips]
        folder = os.path.join(self.dest, "Exports") if self.dest else os.path.dirname(self.clips[0])
        if len(groups) == 1:
            out, _ = QFileDialog.getSaveFileName(self, "Export the video", os.path.join(folder, mixdown.default_name(groups[0])),
                                                 "Videos (*.mp4)")
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
                done.append(mixdown.export(clips, out, b, norm,
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
        forms.show_folder(os.path.dirname(last["out"]))

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
        self._drop_preview()
        super().done(r)
