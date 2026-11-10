"""Builds the music index the Android app reads instead of scanning tags on the phone.

Index format (version 1), written to <library>/index.json:

    {"version": 1, "generated": <ms since epoch>, "root": "coldshift.dash/Music",
     "tracks": [{"p": "folder/song.mp3",   path relative to the music folder, '/' separators, NFC
                 "t": title, "a": artist, "b": album,
                 "d": duration in ms, "n": track number,
                 "s": size in bytes,   the app uses this to notice replaced files
                 "m": mtime in ms,     only used by this tool to skip unchanged files
                 "k": cover key}]}     16 hex chars, names <library>/art/<k>.jpg; "" for none

The cover key is the first 8 bytes of the SHA-1 of the embedded picture, the same scheme the
app uses for its own cache, so identical covers are stored once.
"""
import base64
import hashlib
import io
import json
import os
import re
import time
import unicodedata

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from PIL import Image

from . import layout


def _nfc(s):
    return unicodedata.normalize("NFC", s)


def find_audio(music):
    """Relative paths (NFC, '/' separators) of every audio file, skipping dotfiles."""
    out = []
    for dirpath, dirnames, filenames in os.walk(music):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith(".") or not name.lower().endswith(layout.AUDIO_EXT):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), music)
            out.append(_nfc(rel.replace(os.sep, "/")))
    return out


def unsafe_names(rels):
    """Paths the Huawei G7's Android 4.4 cannot read back correctly.

    Characters outside the basic multilingual plane (emoji, some rare CJK) in a file or folder
    name come back garbled from the card, so the app cannot match them to the index, and two
    names that garble alike collapse into one file. Everything in the BMP is fine, including
    accents, CJK and zero-width spaces.
    """
    return [r for r in rels if any(ord(c) > 0xFFFF for c in r)]


# a joiner, variation selector or keycap mark left behind by an emoji that was replaced
_LEFTOVERS = "\u200d\ufe0f\u20e3"


def _clean(part, is_file):
    if all(ord(c) <= 0xFFFF for c in part):
        return part
    stem, ext = os.path.splitext(part) if is_file else (part, "")
    out, dropped = [], False
    for c in stem:
        if ord(c) > 0xFFFF:
            out.append(" U+%04X " % ord(c))
            dropped = True
            continue
        if c in _LEFTOVERS and (dropped or not out or out[-1] == " "):
            continue
        dropped = False
        out.append(c)
    stem = re.sub(r"\s{2,}", " ", "".join(out)).strip()
    return (stem or ("track" if is_file else "folder")) + ext


def card_name(rel):
    """The name a file gets on the card: `rel` with each character this phone garbles written as its
    code point, in every folder and file name ("Girl 🎶🌸.mp3" -> "Girl U+1F3B6 U+1F338.mp3")."""
    parts = rel.split("/")
    return "/".join(_clean(p, i == len(parts) - 1) for i, p in enumerate(parts))


def card_names(rels):
    """{rel: name on the card} for a whole folder. Names already safe keep theirs; a cleaned name
    that clashes with another (FAT ignores case) gets " (2)", " (3)"... The workspace keeps the
    original names: only the card and the index use these."""
    out, taken = {}, set()
    for rel in rels:
        if card_name(rel) == rel:
            out[rel] = rel
            taken.add(rel.lower())
    for rel in sorted(r for r in rels if r not in out):
        name = card_name(rel)
        stem, ext = os.path.splitext(name)
        n = 2
        while name.lower() in taken:
            name = "%s (%d)%s" % (stem, n, ext)
            n += 1
        out[rel] = name
        taken.add(name.lower())
    return out


def _first(tags, key):
    v = tags.get(key) if tags else None
    if not v:
        return ""
    return str(v[0]).strip()


def _track_no(s):
    try:
        return int(s.split("/")[0])
    except ValueError:
        return 0


def _picture(path, ext):
    """Raw bytes of the embedded cover, preferring the front cover, or None."""
    try:
        if ext == ".mp3":
            pics = ID3(path).getall("APIC")
            if pics:
                front = [p for p in pics if p.type == 3]
                return (front or pics)[0].data
        elif ext == ".flac":
            pics = FLAC(path).pictures
            if pics:
                front = [p for p in pics if p.type == 3]
                return (front or pics)[0].data
        elif ext == ".m4a":
            covr = (MP4(path).tags or {}).get("covr")
            if covr:
                return bytes(covr[0])
        elif ext in (".ogg", ".opus"):
            mf = mutagen.File(path)
            blocks = (mf.tags or {}).get("metadata_block_picture") if mf is not None else None
            if blocks:
                return Picture(base64.b64decode(blocks[0])).data
    except Exception:
        return None
    return None


def _square_jpeg(data):
    im = Image.open(io.BytesIO(data))
    im.draft("RGB", (layout.ART_SIZE * 2, layout.ART_SIZE * 2))
    im = im.convert("RGB")
    side = min(im.size)
    left, top = (im.width - side) // 2, (im.height - side) // 2
    im = im.crop((left, top, left + side, top + side)).resize((layout.ART_SIZE, layout.ART_SIZE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=layout.ART_QUALITY, optimize=True)
    return buf.getvalue()


def read_track(music, rel, art_dir):
    """Entry for one file. Writes its cover into art_dir if it has one and it is not there yet."""
    path = os.path.join(music, *rel.split("/"))
    ext = os.path.splitext(rel)[1].lower()
    st = os.stat(path)
    e = {"p": rel, "t": "", "a": "", "b": "", "d": 0, "n": 0, "s": st.st_size,
         "m": int(st.st_mtime * 1000), "k": ""}
    try:
        easy = mutagen.File(path, easy=True)
    except Exception:
        easy = None
    if easy is not None:
        tags = easy.tags
        e["t"] = _first(tags, "title")
        e["a"] = _first(tags, "artist") or _first(tags, "albumartist")
        e["b"] = _first(tags, "album")
        e["n"] = _track_no(_first(tags, "tracknumber"))
        if easy.info is not None and getattr(easy.info, "length", None):
            e["d"] = int(easy.info.length * 1000)
    pic = _picture(path, ext)
    if pic:
        key = hashlib.sha1(pic).digest()[:8].hex()
        out = os.path.join(art_dir, key + ".jpg")
        if not os.path.exists(out):
            try:
                jpeg = _square_jpeg(pic)          # convert first: a failure must not leave an empty file
            except Exception:
                return e
            tmp = out + ".tmp"
            with open(tmp, "wb") as f:
                f.write(jpeg)
            os.replace(tmp, out)
        e["k"] = key
    return e


def rename_on_card(music):
    """For a music folder that IS the card (in a card reader): renames files to their card names in
    place, so they match the index, and removes folders left empty. Returns [(old, new)]."""
    done = []
    for rel, name in sorted(card_names(find_audio(music)).items()):
        if rel == name:
            continue
        src, dest = os.path.join(music, *rel.split("/")), os.path.join(music, *name.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        os.replace(src, dest)
        done.append((rel, name))
        folder = os.path.dirname(src)
        while folder != os.path.normpath(music) and not os.listdir(folder):
            os.rmdir(folder)
            folder = os.path.dirname(folder)
    return done


def build_index(music, library, progress=None, prune=True):
    """Index `music` into `library` (created if needed). Returns a summary dict; "renamed" lists the
    files whose names the index (and the card) carry without the characters this phone garbles.

    Files whose size and mtime match the previous index are not re-read, so a second run over
    an unchanged folder takes about a second. `progress(done, total, rel)` is called per file.
    """
    art_dir = os.path.join(library, layout.ART_DIR)
    os.makedirs(art_dir, exist_ok=True)
    index_path = os.path.join(library, layout.INDEX_NAME)

    old, old_tracks = {}, None
    if os.path.exists(index_path):
        try:
            with open(index_path, encoding="utf-8") as f:
                old_tracks = json.load(f).get("tracks", [])
            for t in old_tracks:
                old[t["p"]] = t
        except Exception:
            old, old_tracks = {}, None

    started = time.time()
    files = find_audio(music)
    names = card_names(files)          # the index names files as they are on the card
    tracks, reused, read = [], 0, 0
    for i, rel in enumerate(files):
        path = os.path.join(music, *rel.split("/"))
        st = os.stat(path)
        prev = old.get(names[rel])
        if prev and prev.get("s") == st.st_size and prev.get("m") == int(st.st_mtime * 1000) \
                and (not prev.get("k") or os.path.exists(os.path.join(art_dir, prev["k"] + ".jpg"))):
            tracks.append(prev)
            reused += 1
        else:
            e = read_track(music, rel, art_dir)
            e["p"] = names[rel]
            tracks.append(e)
            read += 1
        if progress:
            progress(i + 1, len(files), rel)

    used = {t["k"] for t in tracks if t["k"]}
    pruned = 0
    if prune:
        for name in os.listdir(art_dir):
            if name.endswith(".jpg") and name[:-4] not in used:
                os.remove(os.path.join(art_dir, name))
                pruned += 1

    # An unchanged library keeps its file and its "generated" stamp: the app re-reads the index
    # only when that stamp changes.
    changed = tracks != old_tracks
    if changed:
        doc = {"version": layout.INDEX_VERSION, "generated": int(time.time() * 1000),
               "root": layout.MUSIC_DIR, "tracks": tracks}
        tmp = index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, index_path)
    return {"renamed": sorted((rel, name) for rel, name in names.items() if rel != name), "tracks": len(tracks), "read": read, "reused": reused, "covers": len(used),
            "changed": changed,
            "pruned_covers": pruned, "seconds": round(time.time() - started, 1),
            "index_bytes": os.path.getsize(index_path)}
