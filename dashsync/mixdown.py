"""Mixing a dashcam clip's two sound channels into one, for a video to put online.

With a wireless mic kit in stereo the dashcam's clips carry the engine on the left and the exhaust on the right.
A video wants one mix of them, the same on both channels (so it sounds the same on a phone speaker and in
headphones). This makes that mix with a chosen balance, sets its level, and writes a new .mp4 with the picture
copied as it is (no re-encoding) and the sound in AAC. Several clips can be joined into one video on the way.

- **Balance** runs from -1 (only the left channel) through 0 (both at full level) to +1 (only the right).
- **Level:** the mix is measured first (EBU R128, ffmpeg's loudnorm in measuring mode), then turned up or down by
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


def mix_filter(channels, balance, gain_db=0.0):
    """The ffmpeg audio filter: the mix on both channels, then the level."""
    if channels >= 2:
        gl, gr = gains(balance)
        mix = "%.3f*c0+%.3f*c1" % (gl, gr)
        f = "pan=stereo|c0=%s|c1=%s" % (mix, mix)
    else:
        f = "pan=stereo|c0=c0|c1=c0"
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


def measure(paths, channels, balance, seconds=None, tmpdir=None):
    """(loudness LUFS, true peak dBTP) of the mix at full level; None for either when it is silent."""
    own = tmpdir is None
    tmpdir = tmpdir or tempfile.mkdtemp(prefix="mixdown-")
    try:
        cmd = [_need("ffmpeg"), "-hide_banner", "-nostdin"] + _inputs(paths, tmpdir)
        if seconds:
            cmd += ["-t", "%.2f" % seconds]
        cmd += ["-map", "0:a:0", "-af", mix_filter(channels, balance) + ",loudnorm=print_format=json", "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if r.returncode != 0:
            raise MixError("measuring the sound failed: %s" % (r.stderr or "").strip()[-300:])
        m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr or "")
        if not m:
            return None, None
        j = json.loads(m.group(0))
        return _num(j.get("input_i")), _num(j.get("input_tp"))
    finally:
        if own:
            shutil.rmtree(tmpdir, ignore_errors=True)


def export(paths, out, balance=0.0, normalize=True, progress=None):
    """Writes `out` (.mp4): the clips joined in the order given, the picture copied, the sound mixed.
    `progress(done_s, total_s)` is called as it goes. Returns {"out", "gain_db", "loudness", "peak", "duration"}."""
    if not paths:
        raise MixError("no clips chosen")
    infos, channels = _channels(paths)
    total = sum(i["duration"] for i in infos)
    tmpdir = tempfile.mkdtemp(prefix="mixdown-")
    part = out + ".part.mp4"
    try:
        loudness, peak = measure(paths, channels, balance, tmpdir=tmpdir)
        g = level_gain(loudness, peak, normalize)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        cmd = [_need("ffmpeg"), "-hide_banner", "-nostdin", "-y"] + _inputs(paths, tmpdir)
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


def default_name(paths):
    """"<first clip>.mp4", or "<first> to <last>.mp4" for several."""
    names = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    return (names[0] if len(names) == 1 else "%s to %s" % (names[0], names[-1])) + ".mp4"
