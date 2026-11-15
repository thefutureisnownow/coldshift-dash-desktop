"""Pull dashcam clips, marks and trips off the card into a folder on the Mac.

Destination layout:  <dest>/clips/   loop clips and their .srt and .gcsv (gyro, for Gyroflow) files
                     <dest>/marks/   mark json, gpx and exported mp4
                     <dest>/trips/   trip csv files
                     <dest>/.dashsync-recordings.json   what has been pulled, by size

Rules that protect footage: a file counts as pulled only after the copy's size matches the card;
a file already pulled is not fetched again, even if you later delete the local copy (use
force=True to override); files that are still being written are skipped; and nothing is removed
from the card unless asked (pull with delete_synced=True, or delete_pulled), and then only files
verified in this or an earlier run, and still the same size on the card. delete_pulled keeps
locked clips unless told otherwise.
"""
import datetime
import json
import os
import re
import time

from . import layout

STATE = ".dashsync-recordings.json"
GROUPS = (("clips", "", (".mp4", ".srt", ".gcsv")),
          ("marks", "marks", (".json", ".gpx", ".mp4")),
          ("trips", "trips", (".csv",)),
          ("tests", "tests", (".json",)),
          ("interior", "Interior", (".jpg",)),
          ("sound", "Sound", (".wav", ".csv")))


_WHEN = re.compile(r"(\d{8}_\d{6})")


def describe(key):
    """What a file is, from its name (as the app writes them):
    {"group", "name", "base" (the name without extension: a clip's .mp4 and .srt share it),
     "kind" ("clip", "mark", "trip" or "interior": a photo of the inside from the front camera,
     "sound": the sound recorder's WAV and the engine readings beside it), "when" (datetime in the phone's time, or None), "locked"}."""
    group, _, name = key.partition("/")
    base = name.rsplit(".", 1)[0]
    m = _WHEN.search(name)
    when = None
    if m:
        try:
            when = datetime.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        except ValueError:
            pass
    kind = {"clips": "clip", "marks": "mark", "trips": "trip", "interior": "interior", "sound": "sound"}.get(group, group)
    return {"group": group, "name": name, "base": base, "kind": kind, "when": when,
            "locked": kind == "clip" and base.endswith("_L")}


def sound_channels(dest, base):
    """What is on each channel of a sound recording copied to `dest`, from its CSV's "# channels:" line:
    ["Engine", "Exhaust"] ("" for a channel with no name), or [] when the CSV is not here or older."""
    path = os.path.join(dest, "sound", base + ".csv")
    try:
        with open(path, encoding="utf-8") as f:
            for _ in range(3):
                line = f.readline()
                if line.startswith("# channels:"):
                    return [part.partition("=")[2].strip() for part in line[len("# channels:"):].split(";")]
    except OSError:
        pass
    return []


def _load(dest):
    try:
        with open(os.path.join(dest, STATE), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"files": {}}


def _save(dest, state):
    tmp = os.path.join(dest, STATE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, os.path.join(dest, STATE))


def _scan(target, base):
    """{group/name: (remote_rel, size)} for everything syncable under the Dashcam folder."""
    found = {}
    for group, sub, exts in GROUPS:
        folder = base + ("/" + sub if sub else "")
        for e in target.listdir(folder):
            if e.is_dir or e.name.endswith(".part") or not e.name.lower().endswith(exts):
                continue
            found[group + "/" + e.name] = (folder + "/" + e.name, e.size)
    return found


def _remote_size(target, remote):
    parent, _, name = remote.rpartition("/")
    for e in target.listdir(parent):
        if e.name == name:
            return e.size
    return None


def _settled(target, base, first, wait):
    """Names whose size did not change over `wait` seconds (a clip being written keeps growing)."""
    if wait <= 0:
        return set(first)
    time.sleep(wait)
    second = _scan(target, base)
    return {k for k, (_, size) in first.items() if k in second and second[k][1] == size}


def pull(targets, dest, delete_synced=False, force=False, settle_seconds=None, log=print, dry_run=False,
         progress=None, only=None):
    """Returns {"pulled", "skipped_done", "skipped_busy", "deleted", "bytes", "missing_sources"}.
    `progress(i, n, done_bytes, total_bytes, key)` is called after each file copied. With `only` (keys), just
    those files are looked at."""
    os.makedirs(dest, exist_ok=True)
    state = _load(dest)
    files = state.setdefault("files", {})
    result = {"pulled": 0, "skipped_done": 0, "skipped_busy": 0, "deleted": 0, "bytes": 0, "missing_sources": 0}
    for target in targets:
        base = layout.on_phone(target, layout.DASHCAM_DIR)
        if not target.exists(base):
            result["missing_sources"] += 1
            continue
        found = _scan(target, base)
        if only is not None:
            found = {k: v for k, v in found.items() if k in only}
        wait = settle_seconds if settle_seconds is not None else (2.5 if target.kind == "adb" else 0)
        stable = _settled(target, base, found, wait)
        log("%s: %d files on the card" % (target.label, len(found)))
        todo = [k for k in found if k in stable and not (files.get(k, {}).get("size") == found[k][1] and not force)]
        need, done_bytes, done_n = sum(found[k][1] for k in todo), 0, 0
        for key in sorted(found):
            remote, size = found[key]
            local = os.path.join(dest, *key.split("/"))
            if key not in stable:
                result["skipped_busy"] += 1
                log("  still being written, skipped: %s" % key)
                continue
            done = files.get(key)
            if done and done.get("size") == size and not force:
                result["skipped_done"] += 1
            else:
                if dry_run:
                    log("  would pull %s (%d bytes)" % (key, size))
                    continue
                tmp = local + ".part"
                target.pull(remote, tmp)
                if os.path.getsize(tmp) != size:
                    os.remove(tmp)
                    raise RuntimeError("size mismatch after copying %s: card %d, copy differs" % (key, size))
                os.replace(tmp, local)
                files[key] = {"size": size, "pulled": int(time.time())}
                _save(dest, state)
                result["pulled"] += 1
                result["bytes"] += size
                log("  pulled %s (%.1f MB)" % (key, size / 1048576))
                done_bytes += size
                done_n += 1
                if progress:
                    progress(done_n, len(todo), done_bytes, need, key)
            if delete_synced and not dry_run:
                gone = _delete_if_pulled(target, remote, key, size, files, dest)
                if gone == "deleted":
                    result["deleted"] += 1
                elif gone == "changed":
                    result["skipped_busy"] += 1
                    log("  changed since it was copied, kept on the card: %s" % key)
    return result


def _delete_if_pulled(target, remote, key, size, files, dest):
    """Removes a card file only if it was pulled at this size and the copy is here at that size.
    Returns "deleted", "changed" (it grew or shrank since: unsaved data) or None (not pulled)."""
    local = os.path.join(dest, *key.split("/"))
    if files.get(key, {}).get("size") != size or not os.path.exists(local) or os.path.getsize(local) != size:
        return None
    # look again right before deleting: a file that changed since the copy has data we do not have
    if _remote_size(target, remote) != size:
        return "changed"
    target.remove(remote)
    return "deleted"


def local_files(dest):
    """{key: size} for the recordings copied into `dest` (what is there now, whatever the card holds)."""
    out = {}
    for group, _, exts in GROUPS:
        folder = os.path.join(dest, group)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            p = os.path.join(folder, name)
            if not name.startswith(".") and name.lower().endswith(exts) and os.path.isfile(p):
                out[group + "/" + name] = os.path.getsize(p)
    return out


def status(targets, dest, settle_seconds=None, here_too=False):
    """Everything syncable on the card(s) and whether it is on this computer yet:
    {"items": [describe(key) + {"key", "size", "pulled", "pulled_before", "busy", "source", "remote",
     "on_card"}], "missing_sources": n}.
    "busy" means it is still being written (its size changed while we looked); "remote" is its path on the
    card ("source" names which). With `here_too`, copies here that no card holds any more are items too
    (on_card False, source and remote None, pulled True)."""
    files = _load(dest).get("files", {}) if os.path.isdir(dest) else {}
    items, missing = [], 0
    for target in targets:
        base = layout.on_phone(target, layout.DASHCAM_DIR)
        if not target.exists(base):
            missing += 1
            continue
        found = _scan(target, base)
        wait = settle_seconds if settle_seconds is not None else (2.5 if target.kind == "adb" else 0)
        stable = _settled(target, base, found, wait)
        for key, (remote, size) in sorted(found.items()):
            local = os.path.join(dest, *key.split("/"))
            before = files.get(key, {}).get("size") == size
            pulled = before and os.path.exists(local) and os.path.getsize(local) == size
            # copied once and since removed here: pull does not fetch it again (force=True does)
            items.append(dict(describe(key), key=key, size=size, pulled=pulled, pulled_before=before and not pulled,
                              busy=key not in stable, source=target.label, remote=remote, on_card=True))
    if here_too and os.path.isdir(dest):
        seen = {i["key"] for i in items}
        for key, size in sorted(local_files(dest).items()):
            if key not in seen:
                items.append(dict(describe(key), key=key, size=size, pulled=True, pulled_before=False, busy=False,
                                  source=None, remote=None, on_card=False))
    return {"items": items, "missing_sources": missing}


def delete_here(dest, keys, remove=os.remove):
    """Removes this computer's copies of `keys` (`remove(path)` does it: the app moves them to the Trash). What
    was copied stays noted, so a later pull does not fetch them again. Returns {"deleted", "freed"}."""
    out = {"deleted": 0, "freed": 0}
    for key in keys:
        p = os.path.join(dest, *key.split("/"))
        if os.path.isfile(p):
            size = os.path.getsize(p)
            remove(p)
            out["deleted"] += 1
            out["freed"] += size
    return out


def delete_from_card(targets, items):
    """Removes `items` (status items: their "source" names the target, "remote" the file) from the card,
    whether or not they were copied. A file still being written (its size changed since it was listed) is
    kept. Returns {"deleted", "freed", "kept_changed"}."""
    by_label = {t.label: t for t in targets}
    out = {"deleted": 0, "freed": 0, "kept_changed": 0}
    for i in items:
        t = by_label.get(i.get("source"))
        if not t or not i.get("remote"):
            continue
        size = _remote_size(t, i["remote"])
        if size is None:
            continue                    # gone already
        if size != i["size"]:
            out["kept_changed"] += 1
            continue
        t.remove(i["remote"])
        out["deleted"] += 1
        out["freed"] += size
    return out


def delete_pulled(targets, dest, keep_locked=True, log=print):
    """Frees space on the card: removes files that are safely on this computer (pulled at their
    current size, the copy present). Locked clips stay unless keep_locked=False: a lock means
    "keep this", and the app never loops over them either.
    Returns {"deleted", "freed", "kept_locked", "kept_changed", "not_pulled"}."""
    files = _load(dest).get("files", {}) if os.path.isdir(dest) else {}
    out = {"deleted": 0, "freed": 0, "kept_locked": 0, "kept_changed": 0, "not_pulled": 0}
    for target in targets:
        base = layout.on_phone(target, layout.DASHCAM_DIR)
        if not target.exists(base):
            continue
        for key, (remote, size) in sorted(_scan(target, base).items()):
            if keep_locked and describe(key)["locked"]:
                out["kept_locked"] += 1
                continue
            gone = _delete_if_pulled(target, remote, key, size, files, dest)
            if gone == "deleted":
                out["deleted"] += 1
                out["freed"] += size
            elif gone == "changed":
                out["kept_changed"] += 1
                log("changed since it was copied, kept on the card: %s" % key)
            else:
                out["not_pulled"] += 1
    return out
