"""Small pictures of recordings for the Recordings list: a still from a video 1 s in (ffmpeg), or a photo made
small (Pillow). They are kept in the cache under thumbs/, named by the file's path, size and time, so a file
that changes gets a new one. Without ffmpeg, make() returns None for a video and the app grabs the still itself
(gui/thumbs.py, with Qt's player) and stores it with save()."""
import hashlib
import os
import subprocess

from . import ffmpegtool, paths

WIDTH = 160
VIDEO = (".mp4",)
PHOTO = (".jpg", ".jpeg", ".png")


def folder():
    return os.path.join(paths.cache_dir(), "thumbs")


def path_for(src):
    """Where the small picture of `src` is kept (whether or not it has been made)."""
    st = os.stat(src)
    key = "%s|%d|%d" % (os.path.abspath(src), st.st_size, st.st_mtime_ns)
    return os.path.join(folder(), hashlib.sha1(key.encode("utf-8", "surrogateescape")).hexdigest()[:24] + ".jpg")


def cached(src):
    try:
        p = path_for(src)
    except OSError:
        return None
    return p if os.path.isfile(p) else None


def can_make(src):
    low = src.lower()
    return low.endswith(PHOTO) or (low.endswith(VIDEO) and bool(ffmpegtool.path("ffmpeg")))


def make(src, width=WIDTH):
    """The small picture of `src`, made if it is not there yet; None when it can't be made here (a video without
    ffmpeg, or a file that won't open)."""
    have = cached(src)
    if have:
        return have
    out = path_for(src)
    os.makedirs(folder(), exist_ok=True)
    tmp = out + ".part.jpg"
    low = src.lower()
    try:
        if low.endswith(PHOTO):
            from PIL import Image
            with Image.open(src) as im:
                im = im.convert("RGB")
                im.thumbnail((width, width * 4))
                im.save(tmp, "JPEG", quality=85)
        elif low.endswith(VIDEO):
            ff = ffmpegtool.path("ffmpeg")
            if not ff:
                return None
            for at in ("1", "0"):           # a clip shorter than a second has no frame at 1 s
                subprocess.run([ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-ss", at, "-i", src,
                                "-frames:v", "1", "-vf", "scale=%d:-2" % width, "-q:v", "4", tmp],
                               capture_output=True, timeout=30)
                if os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
                    break
        else:
            return None
        if not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
            return None
        os.replace(tmp, out)
        return out
    except Exception:
        return None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def save(src, write):
    """Stores a picture made elsewhere: `write(path)` writes the JPEG. Returns the path."""
    out = path_for(src)
    os.makedirs(folder(), exist_ok=True)
    tmp = out + ".part.jpg"
    write(tmp)
    os.replace(tmp, out)
    return out
