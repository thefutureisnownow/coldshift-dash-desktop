"""Plays recordings through the system, so the window needs no Qt Multimedia (PySide6-Addons is large).

macOS: afplay. Windows: the MCI player in winmm. Linux: ffplay, mpg123 or mpv, whichever is there.
Playing a list plays the files one after another (a prompt as the app says it); a new play stops the last.
"""
import os
import shutil
import subprocess
import sys
import threading

_lock = threading.Lock()
_proc = None
_gen = 0


def available():
    if sys.platform in ("darwin", "win32"):
        return True
    return any(shutil.which(p) for p in ("ffplay", "mpg123", "mpv"))


def _command(path):
    if sys.platform == "darwin":
        return ["afplay", path]
    for name, args in (("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]), ("mpg123", ["-q"]), ("mpv", ["--no-video", "--really-quiet"])):
        if shutil.which(name):
            return [name] + args + [path]
    return None


def _play_windows(path):
    import ctypes
    mci = ctypes.windll.winmm.mciSendStringW
    mci('close coldshift', None, 0, None)
    mci('open "%s" alias coldshift' % path, None, 0, None)
    mci('play coldshift wait', None, 0, None)
    mci('close coldshift', None, 0, None)


def play(paths):
    """Plays one file or a list of them in the background."""
    global _gen
    if isinstance(paths, str):
        paths = [paths]
    stop()
    with _lock:
        _gen += 1
        gen = _gen

    def run():
        global _proc
        for p in paths:
            with _lock:
                if gen != _gen:
                    return
            if not os.path.exists(p):
                continue
            if sys.platform == "win32":
                _play_windows(p)
                continue
            cmd = _command(p)
            if not cmd:
                return
            with _lock:
                if gen != _gen:
                    return
                _proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                proc = _proc
            proc.wait()
    threading.Thread(target=run, daemon=True).start()


def stop():
    global _proc, _gen
    with _lock:
        _gen += 1
        if _proc is not None and _proc.poll() is None:
            _proc.terminate()
        _proc = None
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.winmm.mciSendStringW('close coldshift', None, 0, None)
        except Exception:
            pass
