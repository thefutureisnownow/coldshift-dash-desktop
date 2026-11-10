"""Find or install ffmpeg and ffprobe, the way adbtool does adb.

Mixing a clip's sound (mixdown) needs both. They are not bundled with the app. `status()` says whether they are
available and where; if not, `setup()` downloads a ready-built copy into the tool's own folder, or the user points
the tool at an existing one with `set_path()` (the folder holding both, or either program in it).

Where the downloads come from (both are listed on ffmpeg.org's download page):
- **macOS and Linux:** Martin Riedl's builds, the latest release, `https://ffmpeg.martin-riedl.de/redirect/latest/
  <macos|linux>/<arm64|amd64>/release/<ffmpeg|ffprobe>.zip`. Each file has its SHA-256 beside it (`.sha256`), and
  the macOS programs are signed.
- **Windows:** BtbN's builds on GitHub, `ffmpeg-master-latest-win64-gpl.zip`, checked against the release's
  `checksums.sha256`.

They are GPL builds of FFmpeg; the tool runs them as separate programs.
"""
import hashlib
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile

from . import paths

EXE = ".exe" if os.name == "nt" else ""
NAMES = ("ffmpeg", "ffprobe")
RIEDL = "https://ffmpeg.martin-riedl.de/redirect/latest/%s/%s/release/%s.zip"
BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
BTBN_ZIP = "ffmpeg-master-latest-win64-gpl.zip"
SOURCE_PAGE = "https://ffmpeg.org/download.html"
_HOMEBREW = ("/opt/homebrew/bin", "/usr/local/bin")


class FfmpegMissing(Exception):
    """ffmpeg is not available; the message says what to do."""


def probe(path, timeout=8):
    """Version string if `path` is a working ffmpeg or ffprobe, else None."""
    try:
        r = subprocess.run([path, "-version"], capture_output=True, text=True, errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"ff(?:mpeg|probe) version (\S+)", r.stdout or "")
    return m.group(1) if r.returncode == 0 and m else None


def own_dir():
    return os.path.join(paths.tools_dir(), "ffmpeg")


def candidates():
    """(source, folder) in the order they are tried."""
    cfg = paths.load_config().get("ffmpeg")
    if cfg:
        yield "chosen in settings", cfg
    yield "downloaded by this tool", own_dir()
    for name in NAMES:
        found = shutil.which(name)
        if found:
            yield "on your PATH", os.path.dirname(found)
    for d in _HOMEBREW:                      # an app opened from the Finder doesn't get the shell's PATH
        yield "Homebrew", d


_found = None


def find(fresh=False):
    """{"ffmpeg", "ffprobe" (paths), "source", "version"} for the first folder holding both working, or None.
    Remembered while those files are still there (each look runs both programs)."""
    global _found
    if not fresh and _found and all(os.path.isfile(_found[n]) for n in NAMES):
        return _found
    _found = _look()
    return _found


def _look():
    seen = set()
    for source, folder in candidates():
        if folder in seen or not os.path.isdir(folder):
            continue
        seen.add(folder)
        exes = [os.path.join(folder, n + EXE) for n in NAMES]
        if not all(os.path.isfile(e) for e in exes):
            continue
        v = probe(exes[0])
        if v and probe(exes[1]):
            return {"ffmpeg": exes[0], "ffprobe": exes[1], "source": source, "version": v}
    return None


def path(name):
    """The path of "ffmpeg" or "ffprobe", or None."""
    f = find()
    return f[name] if f else None


def install_hint():
    own = "Press 'Download ffmpeg' and the tool fetches a ready-built copy for itself."
    if sys.platform == "darwin":
        other = "Or install it yourself with Homebrew: brew install ffmpeg ."
    elif os.name == "nt":
        other = "Or install it yourself, for example: winget install Gyan.FFmpeg ."
    else:
        other = "Or install it with your package manager (the package is called ffmpeg)."
    return own + " " + other + " Already have it? Use 'Choose ffmpeg' and pick its folder."


def status():
    f = find(fresh=True)
    if f:
        return dict(f, found=True, hint="")
    return {"found": False, "ffmpeg": "", "ffprobe": "", "source": "", "version": "", "hint": install_hint()}


def require(name="ffmpeg"):
    p = path(name)
    if not p:
        raise FfmpegMissing("ffmpeg isn't installed, and mixing sound needs it. " + install_hint())
    return p


def set_path(chosen):
    """Remember a user-chosen ffmpeg: the folder holding ffmpeg and ffprobe, or either program in it.
    Raises ValueError if they are not both there and working."""
    folder = os.path.expanduser(chosen)
    if os.path.isfile(folder):
        folder = os.path.dirname(folder)
    exes = [os.path.join(folder, n + EXE) for n in NAMES]
    missing = [os.path.basename(e) for e in exes if not (os.path.isfile(e) and probe(e))]
    if missing:
        raise ValueError("%s has no working %s" % (folder, " or ".join(missing)))
    cfg = paths.load_config()
    cfg["ffmpeg"] = folder
    paths.save_config(cfg)
    find(fresh=True)
    return folder, probe(exes[0])


def forget_path():
    cfg = paths.load_config()
    cfg.pop("ffmpeg", None)
    paths.save_config(cfg)
    find(fresh=True)


# ---- download ----

def _arch():
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "amd64"


def downloads():
    """[(url, expected sha256 or None, the member to take from the zip, the name to save it as)] for this computer.
    The checksum is fetched here (one small request per file)."""
    if os.name == "nt":
        sums = _get_text(BTBN + "checksums.sha256")
        want = next((ln.split()[0] for ln in sums.splitlines() if ln.strip().endswith(BTBN_ZIP)), None)
        if not want:
            raise RuntimeError("BtbN's checksum list has no %s" % BTBN_ZIP)
        inner = BTBN_ZIP[:-4] + "/bin/"
        return [(BTBN + BTBN_ZIP, want.lower(), {inner + "ffmpeg.exe": "ffmpeg.exe", inner + "ffprobe.exe": "ffprobe.exe"})]
    host = "macos" if sys.platform == "darwin" else "linux"
    out = []
    for name in NAMES:
        url = _resolve(RIEDL % (host, _arch(), name))
        want = _get_text(url + ".sha256").split()[0].lower()
        out.append((url, want, {name: name}))
    return out


def _resolve(url):
    """Where a redirect link ends up, so its checksum can be fetched beside it."""
    req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.geturl()


def _get_text(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def setup(progress=None):
    """Downloads ffmpeg and ffprobe for this computer into the tool's own folder. Returns (folder, version).
    `progress(done_bytes, total_bytes)` is called as the files come in (total 0 when the server doesn't say)."""
    items = downloads()
    tools = paths.tools_dir()
    stage = os.path.join(tools, "ffmpeg.new")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    try:
        for url, want, members in items:
            zpath = os.path.join(tools, "ffmpeg-download.zip")
            sha, done = hashlib.sha256(), 0
            with urllib.request.urlopen(url, timeout=60) as r, open(zpath, "wb") as out:
                total = int(r.headers.get("Content-Length") or 0)
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            if want and sha.hexdigest() != want:
                os.remove(zpath)
                raise RuntimeError("the download is corrupt (checksum mismatch); nothing was installed")
            with zipfile.ZipFile(zpath) as z:
                names = z.namelist()
                for member, save_as in members.items():
                    src = member if member in names else next((n for n in names if n.rsplit("/", 1)[-1] == member), None)
                    if not src:
                        raise RuntimeError("%s isn't in the download" % member)
                    with z.open(src) as fin, open(os.path.join(stage, save_as), "wb") as fout:
                        shutil.copyfileobj(fin, fout)
            os.remove(zpath)
        for name in NAMES:
            exe = os.path.join(stage, name + EXE)
            if os.name != "nt":
                os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            if not probe(exe):
                raise RuntimeError("the downloaded %s does not run on this computer" % name)
        target = own_dir()
        shutil.rmtree(target, ignore_errors=True)
        os.replace(stage, target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    find(fresh=True)
    return target, probe(os.path.join(target, "ffmpeg" + EXE))
