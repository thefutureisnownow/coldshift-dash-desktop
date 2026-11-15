"""Drives: the Recordings list's rows gathered into outings, and the readings a trip log holds for a stretch of
time (for the graph under the video in Mix and export).

A drive is a run of recordings with no gap longer than GAP_S between one's end and the next one's start; a trip
log starts a drive of its own (the app starts one each time the car sets off), unless the drive began moments
before it. A recording's end comes from what this computer has of it (tripfiles: a clip's last subtitle, a trip
log's last row, a WAV's length); a clip not copied yet is taken to run CLIP_S, anything else to end where it
starts. Times are the phone's clock, read from the names, as tripfiles reads them.
"""
import csv
import datetime
import os
import re

from . import recordings, tripfiles

GAP_S = 5 * 60
CLIP_S = 181            # the dashcam starts a new clip every 3 minutes or so
TRIP_GRACE_S = 30       # a trip log this soon after a drive's start belongs to it


def _row_span(dest, row):
    """(start, end) in seconds since 1970 for a row of the Recordings list (group_items), or None undated."""
    if not row.get("when"):
        return None
    start = row["when"].timestamp()
    end = start + (CLIP_S if row["kind"] == "clip" else 0)
    for i in row["items"]:
        p = os.path.join(dest, *i["key"].split("/")) if dest else None
        if not p or not os.path.isfile(p):
            continue
        n = tripfiles._length_s(p, i["group"])
        if n is not None:
            end = max(start, n if i["group"] == "trips" else start + n)
    return start, end


def group(rows, dest):
    """The rows gathered into drives, newest first: [{"id", "start", "end", "rows" (newest first)}]. Rows with
    no time in their name make a drive of their own, last ("start" None). A drive's id is its first row's."""
    dated, undated = [], []
    for r in rows:
        s = _row_span(dest, r)
        (dated if s else undated).append((s, r))
    dated.sort(key=lambda x: x[0][0])
    drives = []
    cur = None
    for (start, end), r in dated:
        trip = r["kind"] == "trip"
        new = (cur is None or start > cur["end"] + GAP_S
               or (trip and (cur["trip"] or start > cur["start"] + TRIP_GRACE_S)))
        if new:
            cur = {"id": r["id"], "start": start, "end": end, "rows": [], "trip": False}
            drives.append(cur)
        cur["rows"].append(r)
        cur["end"] = max(cur["end"], end)
        cur["trip"] = cur["trip"] or trip
    for d in drives:
        d["rows"].reverse()
        d.pop("trip")
    drives.reverse()
    if undated:
        drives.append({"id": undated[0][1]["id"], "start": None, "end": None, "rows": [r for _, r in undated]})
    return drives


# ---- trip log readings ----

def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


_loaded = {}


def readings(path):
    """A trip log's readings: [(seconds since 1970, rpm, km/h, throttle %)], None where it has none. Speed is the
    car's (OBD) where it says, else GPS's."""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return []
    if key in _loaded:
        return _loaded[key]
    out = []
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.DictReader(f):
            t = _f(row.get("time_ms"))
            if t is None:
                continue
            kmh = _f(row.get("obd_kmh"))
            if kmh is None and _f(row.get("speed_ms")) is not None:
                kmh = _f(row.get("speed_ms")) * 3.6
            out.append((t / 1000.0, _f(row.get("rpm")), kmh, _f(row.get("throttle_pct"))))
    if len(_loaded) > 8:
        _loaded.clear()
    _loaded[key] = out
    return out


def readings_between(dest, t0, t1):
    """The readings of the trip logs copied to `dest` from t0 to t1 (seconds since 1970), in time order."""
    out = []
    folder = os.path.join(dest, "trips")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        when = recordings.describe("trips/" + name)["when"]
        if not name.endswith(".csv") or not when or when.timestamp() > t1:
            continue
        p = os.path.join(folder, name)
        end = tripfiles._length_s(p, "trips")
        if end is not None and end < t0:
            continue
        out.extend(r for r in readings(p) if t0 <= r[0] <= t1)
    return sorted(out)


_SRT_WHEN = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")


def clip_start(path):
    """When a clip starts (seconds since 1970, the phone's clock): its .srt's first line where it is beside it
    (the time at 0 s), else its name's."""
    srt = os.path.splitext(path)[0] + ".srt"
    try:
        with open(srt, encoding="utf-8", errors="replace") as f:
            for _, line in zip(range(6), f):
                m = _SRT_WHEN.match(line.strip())
                if m:
                    return datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
    except (OSError, ValueError):
        pass
    when = recordings.describe("clips/" + os.path.basename(path))["when"]
    return when.timestamp() if when else None


def joined(paths, dest, durations):
    """The clips joined end to end, as Mix and export plays and exports them: (total seconds, where each clip after
    the first starts, the trip log's readings with their times moved onto the joined clips)."""
    offsets, t = [], 0.0
    for d in durations:
        offsets.append(t)
        t += d
    starts = [clip_start(p) for p in paths]
    known = [(s, d, off) for s, d, off in zip(starts, durations, offsets) if s is not None]
    samples = []
    if known and dest:
        found = readings_between(dest, min(s for s, _, _ in known), max(s + d for s, d, _ in known))
        for s, d, off in known:
            samples.extend((off + r[0] - s,) + tuple(r[1:]) for r in found if s <= r[0] <= s + d)
    return t, offsets[1:], sorted(samples)
