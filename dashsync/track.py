"""Track segments and runs on the computer: copied from the phone, compared, shared.

The app keeps them in its folder on the card (TrackStore.java):
    <card>/Android/data/racing.coldshift.dash/files/track/segments/<id>.json
        {"version": 1, "id", "name", "created", "points": [[lat, lon], ...]}
    .../track/runs/<id>/<start>-<lap>.json
        {"version": 1, "segment", "start", "time_ms", "lap", "mark", "t": [s], "d": [m], "speed": [m/s]}
`sync_to_pc` copies them into <vehicle>/track/ (the same layout; runs the phone no longer has are kept
here). `sync_to_card` puts this vehicle's segments in <card>/coldshift.dash/track/segments/, from where
the app takes in new ones and renames. A segment is shared as a .segment.json file (or GPX); a run is
shared as a folder with its clip (the dashcam mark's export, from the Recordings folder), its GPX and CSV.
"""
import datetime
import json
import math
import os
import re
import shutil
import time
from xml.sax.saxutils import escape

from . import layout

PHONE = layout.APP_DATA + "/track"
SHARED = layout.APP_DIR + "/track/segments"
LAP_JOIN_M = 50
R = 6371000


def dist(a, b):
    x = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    y = math.radians(b[0] - a[0])
    return math.hypot(x, y) * R


def _dir(vehicle, *parts):
    return os.path.join(vehicle, "track", *parts)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(path + ".part", path)


# ---- segments and runs here ----

def _segment(data, path=None):
    pts = [tuple(p) for p in data["points"]]
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + dist(pts[i - 1], pts[i]))
    lap = len(pts) > 2 and dist(pts[0], pts[-1]) < LAP_JOIN_M and cum[-1] > 4 * LAP_JOIN_M
    return {"id": data["id"], "name": data.get("name") or data["id"], "created": data.get("created", 0),
            "points": pts, "cum": cum, "length": cum[-1], "lap": lap, "file": path}


def segments(vehicle):
    """This vehicle's segments, newest first, each with its runs' count and best time."""
    out = []
    d = _dir(vehicle, "segments")
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith(".json"):
            continue
        try:
            s = _segment(_read(os.path.join(d, name)), os.path.join(d, name))
        except (OSError, ValueError, KeyError):
            continue
        rs = runs(vehicle, s["id"])
        s["runs"] = len(rs)
        s["best_ms"] = min((r["time_ms"] for r in rs), default=None)
        out.append(s)
    return sorted(out, key=lambda s: -s["created"])


def segment(vehicle, sid):
    for s in segments(vehicle):
        if s["id"] == sid:
            return s
    raise ValueError("no segment %s" % sid)


def runs(vehicle, sid):
    """A segment's runs, newest first, with their traces."""
    out = []
    d = _dir(vehicle, "runs", sid)
    for name in os.listdir(d) if os.path.isdir(d) else []:
        if not name.endswith(".json"):
            continue
        try:
            r = _read(os.path.join(d, name))
            r["file"] = os.path.join(d, name)
            out.append(r)
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda r: (-r["start"], -r.get("lap", 0)))


def rename(vehicle, sid, name):
    name = name.strip()
    if not name:
        raise ValueError("give the segment a name")
    path = _dir(vehicle, "segments", sid + ".json")
    data = _read(path)
    data["name"] = name
    _write(path, data)


def delete(vehicle, sid):
    """Takes a segment and its runs off this computer (the phone keeps its own until deleted there)."""
    path = _dir(vehicle, "segments", sid + ".json")
    if os.path.exists(path):
        os.remove(path)
    shutil.rmtree(_dir(vehicle, "runs", sid), ignore_errors=True)


# ---- the phone ----

def sync_to_pc(target, vehicle):
    """Copies the phone's segments and runs that are new or changed. Returns {"segments", "runs"} copied."""
    out = {"segments": 0, "runs": 0}
    phone = layout.on_phone(target, PHONE)
    for e in target.listdir(phone + "/segments"):
        if e.name.endswith(".json"):
            local = _dir(vehicle, "segments", e.name)
            if not os.path.exists(local) or os.path.getsize(local) != e.size:
                # a name changed here and not yet on the phone stays
                keep = _read(local).get("name") if os.path.exists(local) else None
                target.pull(phone + "/segments/" + e.name, local)
                if keep and keep != _read(local).get("name") and _pending_name(vehicle, e.name[:-5]):
                    rename(vehicle, e.name[:-5], keep)
                out["segments"] += 1
    for seg in target.listdir(phone + "/runs"):
        if not seg.is_dir:
            continue
        for e in target.listdir(phone + "/runs/" + seg.name):
            local = _dir(vehicle, "runs", seg.name, e.name)
            if e.name.endswith(".json") and (not os.path.exists(local) or os.path.getsize(local) != e.size):
                target.pull(phone + "/runs/" + seg.name + "/" + e.name, local)
                out["runs"] += 1
    return out


def _pending_name(vehicle, sid):
    return sid in _read_pending(vehicle)


def _read_pending(vehicle):
    try:
        return set(_read(_dir(vehicle, "renamed.json")))
    except (OSError, ValueError):
        return set()


def mark_renamed(vehicle, sid):
    """Remembers a name changed here until it is synced to the card (so a sync to the PC keeps it)."""
    p = _read_pending(vehicle) | {sid}
    _write(_dir(vehicle, "renamed.json"), sorted(p))


def sync_to_card(target, vehicle):
    """Puts this vehicle's segments where the app takes them in. Returns {"segments", "app"}."""
    mine = {s["id"] + ".json": s["file"] for s in segments(vehicle)}
    have = {e.name: e.size for e in target.listdir(SHARED)}
    copied = 0
    for name, path in mine.items():
        if have.get(name) != os.path.getsize(path):
            target.push(path, SHARED + "/" + name)
            copied += 1
    for name in set(have) - set(mine):
        target.remove(SHARED + "/" + name)
    if os.path.exists(_dir(vehicle, "renamed.json")):
        os.remove(_dir(vehicle, "renamed.json"))
    reply = target.notify_synced(["track"]) if copied else None
    return {"segments": len(mine), "copied": copied, "app": reply}


# ---- sharing segments ----

def export_segment(vehicle, sid, path):
    s = segment(vehicle, sid)
    _write(path, {"type": "coldshift.dash segment", "version": 1, "name": s["name"],
                  "points": [[round(a, 6), round(b, 6)] for a, b in s["points"]]})
    return path


def import_segment(vehicle, path, name=None):
    """Adds a shared segment: a .segment.json from this tool, or any GPX with a track or route."""
    if path.lower().endswith(".gpx"):
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        pts = [(float(a), float(b)) for a, b in re.findall(
            r'<(?:trkpt|rtept)\b[^>]*?lat="([-\d.]+)"[^>]*?lon="([-\d.]+)"', text)]
        pts += [(float(a), float(b)) for b, a in re.findall(
            r'<(?:trkpt|rtept)\b[^>]*?lon="([-\d.]+)"[^>]*?lat="([-\d.]+)"', text)]
        m = re.search(r"<name>([^<]+)</name>", text)
        default = m.group(1).strip() if m else os.path.splitext(os.path.basename(path))[0]
    else:
        data = _read(path)
        if data.get("type") != "coldshift.dash segment" and "points" not in data:
            raise ValueError("%s is not a segment" % os.path.basename(path))
        pts = [tuple(p) for p in data["points"]]
        default = data.get("name") or os.path.basename(path).split(".")[0]
    if len(pts) < 3:
        raise ValueError("%s has no path in it" % os.path.basename(path))
    sid = "seg-%d" % int(time.time() * 1000)
    _write(_dir(vehicle, "segments", sid + ".json"),
           {"version": 1, "id": sid, "name": name or default, "created": int(time.time() * 1000),
            "points": [[round(a, 6), round(b, 6)] for a, b in pts]})
    return sid


def segment_gpx(s):
    pts = "".join('<trkpt lat="%.6f" lon="%.6f"/>' % p for p in s["points"])
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="coldshift.dash" '
            'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>%s</name><trkseg>%s</trkseg></trk></gpx>\n'
            % (escape(s["name"]), pts))


# ---- runs ----

def position(s, metres):
    """(lat, lon) at a distance along the segment's path."""
    cum, pts = s["cum"], s["points"]
    metres = max(0, min(metres, cum[-1]))
    for i in range(1, len(cum)):
        if cum[i] >= metres:
            span = cum[i] - cum[i - 1]
            f = 0 if span <= 0 else (metres - cum[i - 1]) / span
            return (pts[i - 1][0] + f * (pts[i][0] - pts[i - 1][0]), pts[i - 1][1] + f * (pts[i][1] - pts[i - 1][1]))
    return pts[-1]


def run_gpx(s, r):
    """The run as a GPX track with times (overlay tools such as RaceRender read these)."""
    rows = []
    for t, d, v in zip(r["t"], r["d"], r["speed"]):
        lat, lon = position(s, d)
        when = datetime.datetime.fromtimestamp(r["start"] / 1000 + t, datetime.timezone.utc)
        rows.append('<trkpt lat="%.6f" lon="%.6f"><time>%s</time><extensions><speed>%.2f</speed></extensions></trkpt>'
                    % (lat, lon, when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-4] + "Z", v))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="coldshift.dash" '
            'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>%s %s</name><trkseg>%s</trkseg></trk></gpx>\n'
            % (escape(s["name"]), time_text(r["time_ms"] / 1000), "".join(rows)))


def run_csv(s, r):
    lines = ["time_s,distance_m,speed_kmh,lat,lon"]
    for t, d, v in zip(r["t"], r["d"], r["speed"]):
        lat, lon = position(s, d)
        lines.append("%.2f,%.1f,%.1f,%.6f,%.6f" % (t, d, v * 3.6, lat, lon))
    return "\n".join(lines) + "\n"


def time_at(r, metres):
    """A run's time at a distance (interpolated), or None beyond its end."""
    d, t = r["d"], r["t"]
    if not d or metres > d[-1]:
        return None
    for i in range(1, len(d)):
        if d[i] >= metres:
            span = d[i] - d[i - 1]
            f = 0 if span <= 0 else (metres - d[i - 1]) / span
            return t[i - 1] + f * (t[i] - t[i - 1])
    return t[-1]


def speed_at(r, metres):
    d, v = r["d"], r["speed"]
    for i in range(1, len(d)):
        if d[i] >= metres:
            span = d[i] - d[i - 1]
            f = 0 if span <= 0 else (metres - d[i - 1]) / span
            return v[i - 1] + f * (v[i] - v[i - 1])
    return v[-1] if v else 0


def compare(a, b, length, step=5):
    """Over the distance: [(metres, b's time minus a's (negative: b ahead), a's km/h, b's km/h)]."""
    out = []
    m = 0.0
    while m <= length:
        ta, tb = time_at(a, m), time_at(b, m)
        if ta is not None and tb is not None:
            out.append((m, tb - ta, speed_at(a, m) * 3.6, speed_at(b, m) * 3.6))
        m += step
    return out


def time_text(s):
    if s is None:
        return "-"
    m, rest = divmod(s, 60)
    return "%d:%04.1f" % (m, rest) if m else "%.1f" % rest


def recordings_dir(cfg):
    return cfg.get("recordings") or (os.path.join(cfg["workspace"], "recordings") if cfg.get("workspace") else None)


def clip(recordings, mark):
    """The run's video: the dashcam mark's export among the copied recordings, or None."""
    d = os.path.join(recordings or "", "marks")
    if not mark or not os.path.isdir(d):
        return None
    for name in sorted(os.listdir(d)):
        if name.startswith("mark_%04d_" % mark) and name.endswith(".mp4"):
            return os.path.join(d, name)
    return None


def share_run(vehicle, sid, run_file, dest_root, recordings=None):
    """A folder to share a run: its clip (if copied from the phone), GPX and CSV, the segment's GPX and a
    note. Returns (folder, whether the clip is in it)."""
    s = segment(vehicle, sid)
    r = [x for x in runs(vehicle, sid) if x["file"] == run_file][0]
    when = datetime.datetime.fromtimestamp(r["start"] / 1000)
    name = "%s %s %s" % (s["name"], when.strftime("%Y-%m-%d %H.%M"), ("lap %d" % r["lap"]) if r.get("lap") else "")
    folder = os.path.join(dest_root, re.sub(r'[\\/:*?"<>|]', "-", name).strip())
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "run.gpx"), "w", encoding="utf-8") as f:
        f.write(run_gpx(s, r))
    with open(os.path.join(folder, "run.csv"), "w", encoding="utf-8") as f:
        f.write(run_csv(s, r))
    with open(os.path.join(folder, "segment.gpx"), "w", encoding="utf-8") as f:
        f.write(segment_gpx(s))
    video = clip(recordings, r.get("mark"))
    if video:
        shutil.copyfile(video, os.path.join(folder, "clip.mp4"))
    with open(os.path.join(folder, "about.txt"), "w", encoding="utf-8") as f:
        f.write("%s: %s on %s (%s, %.0f m)\n" % (s["name"], time_text(r["time_ms"] / 1000), when.strftime("%d %b %Y %H:%M"),
                                                 "lap %d" % r["lap"] if r.get("lap") else "point to point", s["length"]))
        f.write("clip.mp4 starts about 3 s before the start line.\n" if video else "")
        f.write("run.gpx and run.csv: time, distance and speed at each GPS fix (once a second), for overlay tools.\n")
        f.write("segment.gpx: the segment's path, to import as a segment in coldshift.dash or elsewhere.\n")
    return folder, bool(video)
