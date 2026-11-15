"""Mixing a dashcam clip's two sound channels into one, for a video to put online.

With a wireless mic kit in stereo the dashcam's clips carry the engine on the left and the exhaust on the right.
A video wants one mix of them, the same on both channels (so it sounds the same on a phone speaker and in
headphones). This makes that mix with a chosen balance, sets its level, and writes a new .mp4 with the picture
copied as it is (no re-encoding) and the sound in AAC. Several clips can be joined into one video on the way.

- **Balance** runs from -1 (only the left channel) through 0 (both at full level) to +1 (only the right).
- **Level:** the mix is measured first (EBU R128, ffmpeg's ebur128 with true peaks), then turned up or down by
  one fixed amount, so the revs keep their shape: to -14 LUFS (where YouTube plays things) when `normalize`,
  but never so far that the loudest peak goes above -1 dBTP. Without `normalize` it is only turned down, if a peak
  would go over.
- **A clip with one channel** (the phone's own mic) is put on both channels as it is.
- **Needs ffmpeg and ffprobe,** found or downloaded by ffmpegtool (they are not bundled).
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading

from . import ffmpegtool

TARGET_LUFS = -14.0
CEILING_DBTP = -1.0
AUDIO_BITRATE = "192k"
# ffmpeg's AAC encoder fills some bands with noise of its own on each channel (PNS), so two identical channels
# come out slightly different; without it, and coded as mid/side, they stay exactly the same
SAME_ON_BOTH = ["-aac_pns", "0", "-aac_is", "0", "-aac_ms", "1"]


class MixError(Exception):
    """Something the user can act on; the message says what."""


def tool(name):
    """The path of ffmpeg or ffprobe, or None."""
    return ffmpegtool.path(name)


def _need(name):
    p = tool(name)
    if not p:
        raise MixError("ffmpeg isn't installed, and mixing sound needs it. " + ffmpegtool.install_hint())
    return p


def probe(path):
    """{"duration": seconds, "channels": the first sound stream's channels (0 without sound), "video": bool}."""
    r = subprocess.run([_need("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise MixError("can't read %s: %s" % (os.path.basename(path), (r.stderr or "").strip()[:200]))
    info = json.loads(r.stdout or "{}")
    streams = info.get("streams", [])
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    try:
        duration = float(info.get("format", {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    return {"duration": duration, "channels": int(audio[0].get("channels", 0)) if audio else 0,
            "video": any(s.get("codec_type") == "video" for s in streams)}


def gains(balance):
    """(left, right) gains for a balance from -1 (left only) to +1 (right only); 0 is both at full level."""
    b = max(-1.0, min(1.0, float(balance)))
    return min(1.0, 1.0 - b), min(1.0, 1.0 + b)


def mix_filter(channels, balance, gain_db=0.0, mono=False):
    """The ffmpeg audio filter: the mix on both channels (or on one, `mono`), then the level."""
    if channels >= 2:
        gl, gr = gains(balance)
        mix = "%.3f*c0+%.3f*c1" % (gl, gr)
    else:
        mix = "c0"
    f = ("pan=mono|c0=%s" % mix) if mono else ("pan=stereo|c0=%s|c1=%s" % (mix, mix))
    return f + ",volume=%.2fdB" % gain_db


def level_gain(loudness, peak, normalize=True, target=TARGET_LUFS, ceiling=CEILING_DBTP):
    """dB to add: toward `target` when normalizing (else none), and never past `ceiling` at the loudest peak.
    `loudness` and `peak` are None for silence."""
    g = (target - loudness) if (normalize and loudness is not None) else 0.0
    if peak is not None:
        g = min(g, ceiling - peak)
    return max(-30.0, min(30.0, g))


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def _inputs(paths, tmpdir):
    """ffmpeg input arguments for one file or several joined (the concat demuxer: same codecs, no re-encoding)."""
    if len(paths) == 1:
        return ["-i", paths[0]]
    lst = os.path.join(tmpdir, "clips.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in paths:
            f.write("file '%s'\n" % os.path.abspath(p).replace("'", "'\\''"))
    return ["-f", "concat", "-safe", "0", "-i", lst]


def _channels(paths):
    infos = [probe(p) for p in paths]
    counts = {i["channels"] for i in infos}
    if counts == {0}:
        raise MixError("these clips have no sound")
    if len(counts) > 1:
        raise MixError("these clips can't be joined: some have %s" % " and some ".join(
            "no sound" if c == 0 else "one sound channel" if c == 1 else "%d sound channels" % c for c in sorted(counts)))
    return infos, counts.pop()


def _from(start):
    """ffmpeg's input arguments to begin `start` seconds in (before -i: a seek, to the keyframe before it when the
    picture is copied; the dashcam makes one every second)."""
    return ["-ss", "%.3f" % start] if start else []


def measure(paths, channels, balance, seconds=None, tmpdir=None, start=None):
    """(loudness LUFS, true peak dBTP) of the mix at full level; None for either when it is silent."""
    own = tmpdir is None
    tmpdir = tmpdir or tempfile.mkdtemp(prefix="mixdown-")
    try:
        cmd = [_need("ffmpeg"), "-hide_banner", "-nostdin"] + _from(start) + _inputs(paths, tmpdir)
        if seconds:
            cmd += ["-t", "%.2f" % seconds]
        # ebur128 reads what loudnorm's measuring pass does (the same figures) in a fifth of the time
        cmd += ["-map", "0:a:0", "-af", mix_filter(channels, balance) + ",ebur128=peak=true:framelog=quiet",
                "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if r.returncode != 0:
            raise MixError("measuring the sound failed: %s" % (r.stderr or "").strip()[-300:])
        summary = (r.stderr or "").rpartition("Summary:")[2]
        i = re.search(r"\bI:\s+(-?[\d.]+|-?inf) LUFS", summary)
        tp = re.search(r"\bPeak:\s+(-?[\d.]+|-?inf) dBFS", summary)
        loudness = _num(i.group(1)) if i else None
        if loudness is not None and loudness <= -70:
            loudness = None                         # ebur128's floor: nothing above its gate, silence
        return loudness, (_num(tp.group(1)) if tp else None)
    finally:
        if own:
            shutil.rmtree(tmpdir, ignore_errors=True)


def trimmed(total, start=None, end=None):
    """(start, seconds) of the part to export from a joined length `total`; (None, None) for all of it."""
    s = max(0.0, float(start or 0))
    e = min(total, float(end)) if end else total
    if e - s < 0.5:
        raise MixError("the part to export is shorter than half a second")
    return (s or None), (None if (s == 0 and e >= total) else e - s)


def export(paths, out, balance=0.0, normalize=True, progress=None, start=None, end=None):
    """Writes `out` (.mp4): the clips joined in the order given, the picture copied, the sound mixed; with
    `start` and `end` (seconds into the joined clips) only that part. `progress(done_s, total_s)` is called as it
    goes. Returns {"out", "gain_db", "loudness", "peak", "duration"}."""
    if not paths:
        raise MixError("no clips chosen")
    infos, channels = _channels(paths)
    start, seconds = trimmed(sum(i["duration"] for i in infos), start, end)
    total = seconds or sum(i["duration"] for i in infos) - (start or 0)
    tmpdir = tempfile.mkdtemp(prefix="mixdown-")
    part = out + ".part.mp4"
    try:
        loudness, peak = measure(paths, channels, balance, seconds=seconds, tmpdir=tmpdir, start=start)
        g = level_gain(loudness, peak, normalize)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        cmd = [_need("ffmpeg"), "-hide_banner", "-nostdin", "-y"] + _from(start) + _inputs(paths, tmpdir)
        if seconds:
            cmd += ["-t", "%.3f" % seconds]
        cmd += ["-map", "0:v:0?", "-map", "0:a:0", "-c:v", "copy", "-af", mix_filter(channels, balance, g),
                "-c:a", "aac", "-b:a", AUDIO_BITRATE] + SAME_ON_BOTH + [
                "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", part]
        err = []
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace") as proc:
            def drain():
                for line in proc.stderr:
                    err.append(line)
            t = threading.Thread(target=drain, daemon=True)
            t.start()
            for line in proc.stdout:
                if line.startswith("out_time_us=") and progress:
                    us = _num(line.split("=", 1)[1])
                    if us is not None and us >= 0:
                        progress(min(total, us / 1e6), total)
            proc.wait()
            t.join(timeout=5)
        if proc.returncode != 0:
            raise MixError("ffmpeg stopped: %s" % "".join(err).strip()[-400:])
        os.replace(part, out)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        if os.path.exists(part):
            os.remove(part)
    if progress:
        progress(total, total)
    return {"out": out, "gain_db": g, "loudness": loudness, "peak": peak, "duration": total}


def preview(path, balance=0.0, normalize=True, seconds=20.0, start=0.0):
    """A WAV of the mix from `start` for `seconds`, to listen to before exporting; the caller deletes it."""
    channels = probe(path)["channels"]
    if channels == 0:
        raise MixError("this clip has no sound")
    loudness, peak = measure([path], channels, balance, seconds=seconds)
    g = level_gain(loudness, peak, normalize)
    fd, wav = tempfile.mkstemp(prefix="mix-preview-", suffix=".wav")
    os.close(fd)
    cmd = [_need("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-ss", "%.2f" % start, "-i", path, "-t", "%.2f" % seconds,
           "-map", "0:a:0", "-af", mix_filter(channels, balance, g), wav]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        os.remove(wav)
        raise MixError("making the preview failed: %s" % (r.stderr or "").strip()[-300:])
    return wav


def durations(paths):
    """Each clip's length in seconds."""
    return [probe(p)["duration"] for p in paths]


def extract(paths, wav):
    """The clips' sound joined, as recorded (every channel), into `wav`: read once from the videos, so the mix can
    be made again from it in a moment each time the balance changes (render's `source`)."""
    _channels(paths)
    tmpdir = tempfile.mkdtemp(prefix="mixdown-")
    part = wav + ".part.wav"
    try:
        r = subprocess.run([_need("ffmpeg"), "-hide_banner", "-nostdin", "-y"] + _inputs(paths, tmpdir) +
                           ["-map", "0:a:0", "-vn", "-c:a", "pcm_s16le", part],
                           capture_output=True, text=True, errors="replace")
        if r.returncode != 0:
            raise MixError("reading the clips' sound failed: %s" % (r.stderr or "").strip()[-300:])
        os.replace(part, wav)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        if os.path.exists(part):
            os.remove(part)


def render(paths, wav, balance=0.0, normalize=True, source=None):
    """The mix of the clips joined, as `wav` (one channel: the same goes on both), at the level export gives it:
    what the player in Mix and export plays beside the picture. With `source` (extract's WAV of the same clips)
    it is made from that, much faster. Returns the dB added."""
    if source:
        import wave
        with wave.open(source) as w:
            channels = w.getnchannels()
        paths = [source]
    else:
        _, channels = _channels(paths)
    tmpdir = tempfile.mkdtemp(prefix="mixdown-")
    try:
        loudness, peak = measure(paths, channels, balance, tmpdir=tmpdir)
        g = level_gain(loudness, peak, normalize)
        part = wav + ".part.wav"
        cmd = [_need("ffmpeg"), "-hide_banner", "-nostdin", "-y"] + _inputs(paths, tmpdir) + [
            "-map", "0:a:0", "-af", mix_filter(channels, balance, g, mono=True), "-c:a", "pcm_s16le", part]
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if r.returncode != 0:
            if os.path.exists(part):
                os.remove(part)
            raise MixError("making the mix failed: %s" % (r.stderr or "").strip()[-300:])
        os.replace(part, wav)
        return g
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def default_name(paths):
    """"<first clip>.mp4", or "<first> to <last>.mp4" for several."""
    names = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    return (names[0] if len(names) == 1 else "%s to %s" % (names[0], names[-1])) + ".mp4"
