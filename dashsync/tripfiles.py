"""Gathering one log book trip's files into a folder of their own: the dashcam's clips (with their .srt), marks,
the dashcam's trip log, sound recordings (with their readings), interior shots, and the trip's route.

They are found in the copy the Recordings tab keeps (recordings.pull puts them in <dest>/<group>/), by time: a
file's start comes from its name (the phone's clock), and its end from what it holds where that says (a WAV's
length, the last row of a trip log, the last subtitle of a clip); a clip without one is taken to run up to
LONGEST_S. A file belongs to the trip when it overlaps the trip's start and end.

The folder is <dest>/Trip folders/<date time> <from> to <to>/ with the files under the same group names, the
route as route.csv and route.gpx, and trip.txt saying what the trip was and what is there. Gathering again
copies only what the folder lacks.
"""
import datetime
import os
import re
import shutil
import wave

from . import logbook, recordings

FOLDER = "Trip folders"
LONGEST_S = 10 * 60             # a clip or a sound file is never longer than this (the app splits them)


def _epoch(when):
    return when.timestamp() if when else None


def _last_line(path):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 4096))
        lines = [ln for ln in f.read().decode("utf-8", "replace").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


_SRT = re.compile(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> ")


def _length_s(path, group):
    """How long a copied file runs in seconds, from what it holds; None when it does not say."""
    try:
        if group == "sound" and path.endswith(".wav"):
            with wave.open(path) as w:
                return w.getnframes() / float(w.getframerate())
        if group == "clips" and path.endswith(".srt"):
            last = None
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = _SRT.match(line)
                    if m:
                        last = m
            if last:
                h, mi, s, ms = (int(x) for x in last.groups())
                return h * 3600 + mi * 60 + s + ms / 1000 + 1
        if group == "trips" and path.endswith(".csv"):
            t = _last_line(path).split(",")[0]
            return None if not t.isdigit() else int(t) / 1000      # an end time, not a length: see spans()
    except (OSError, EOFError, wave.Error, ValueError):
        pass
    return None


def spans(dest):
    """The recordings copied to `dest`, one per recording (a clip's .mp4 and .srt together):
    [{"group", "base", "files": [relative paths], "start", "end"}], times in seconds since 1970."""
    by = {}
    for group, _sub, exts in recordings.GROUPS:
        folder = os.path.join(dest, group)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(exts) or name.endswith(".part"):
                continue
            d = recordings.describe(group + "/" + name)
            start = _epoch(d["when"])
            if start is None:
                continue
            r = by.setdefault((group, d["base"]), {"group": group, "base": d["base"], "files": [], "start": start,
                                                   "end": None})
            r["files"].append(group + "/" + name)
            n = _length_s(os.path.join(folder, name), group)
            if n is not None:
                end = n if group == "trips" else start + n
                r["end"] = max(r["end"] or 0, end)
    out = []
    for r in by.values():
        if r["end"] is None:
            r["end"] = r["start"] if r["group"] == "interior" else r["start"] + LONGEST_S
        out.append(r)
    return sorted(out, key=lambda r: (r["start"], r["group"]))


def matching(dest, trip):
    """The recordings in `dest` that overlap the trip."""
    t0, t1 = trip["time"] / 1000, (trip.get("end") or trip["time"]) / 1000
    return [r for r in spans(dest) if r["start"] <= t1 and r["end"] >= t0]


def _safe(s):
    s = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", s).strip(" .")
    return re.sub(r"\s+", " ", s)[:80]


def folder_name(trip):
    when = datetime.datetime.fromtimestamp(trip["time"] / 1000).strftime("%Y-%m-%d %H%M")
    a, b = logbook._place(trip, "from"), logbook._place(trip, "to")
    ends = (" %s to %s" % (a or "?", b or "?")) if (a or b) else ""
    return _safe(when + ends)


def gather(vehicle, dest, trip, log=print):
    """Copies the trip's recordings from `dest` into its folder, with its route and trip.txt. Returns
    {"folder", "copied", "had", "bytes", "recordings": [span], "route": points}."""
    folder = os.path.join(dest, FOLDER, folder_name(trip))
    os.makedirs(folder, exist_ok=True)
    found = matching(dest, trip)
    out = {"folder": folder, "copied": 0, "had": 0, "bytes": 0, "recordings": found, "route": 0}
    for r in found:
        for rel in r["files"]:
            src = os.path.join(dest, *rel.split("/"))
            dst = os.path.join(folder, *rel.split("/"))
            if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
                out["had"] += 1
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst + ".part")
            os.replace(dst + ".part", dst)
            out["copied"] += 1
            out["bytes"] += os.path.getsize(dst)
            log("  copied %s" % rel)
    points = logbook.route(vehicle, trip["id"]) if vehicle else []
    if points:
        with open(os.path.join(folder, "route.csv"), "w", encoding="utf-8") as f:
            f.write("time_ms,lat,lon,speed_ms\n")
            for ms, la, lo, v in points:
                f.write("%d,%.6f,%.6f,%.1f\n" % (ms, la, lo, v))
        logbook.export_gpx(vehicle, [trip], os.path.join(folder, "route.gpx"))
        out["route"] = len(points)
    with open(os.path.join(folder, "trip.txt"), "w", encoding="utf-8") as f:
        f.write(summary(dest, trip, found, len(points)))
    return out


KIND = {"clips": "Dashcam clip", "marks": "Mark", "trips": "Dashcam trip log", "interior": "Interior shot",
        "sound": "Sound"}


def summary(dest, trip, found, route_points):
    """trip.txt: the trip, then each recording with its time, length and files."""
    t0 = datetime.datetime.fromtimestamp(trip["time"] / 1000)
    t1 = datetime.datetime.fromtimestamp((trip.get("end") or trip["time"]) / 1000)
    mins = int((t1 - t0).total_seconds() // 60)
    lines = ["Trip %s, %s to %s (%d h %02d min)" % (t0.strftime("%a %d %b %Y"), t0.strftime("%H:%M"), t1.strftime("%H:%M"),
                                                    mins // 60, mins % 60),
             "From: %s" % (logbook._place(trip, "from") or "?"),
             "To:   %s" % (logbook._place(trip, "to") or "?"),
             "GPS distance: %.1f km   Top speed: %.0f km/h" % ((trip.get("dist_m") or 0) / 1000, (trip.get("max") or 0) * 3.6),
             ("Business: " + trip.get("purpose", "")) if trip.get("business") else "Private",
             "Route: %s" % ("route.csv and route.gpx, %d points" % route_points if route_points else "none kept for this trip"),
             "", "Recordings (the phone's clock):"]
    if not found:
        lines.append("  none in the copy on this computer (if the phone recorded during the trip, Recordings → Sync to PC")
        lines.append("  copies them; gathering again adds them)")
    for r in found:
        s = datetime.datetime.fromtimestamp(r["start"]).strftime("%H:%M:%S")
        e = datetime.datetime.fromtimestamp(r["end"]).strftime("%H:%M:%S")
        what = KIND.get(r["group"], r["group"])
        if r["group"] == "sound":
            names = [n for n in recordings.sound_channels(dest, r["base"]) if n]
            if names:
                what += " (" + " / ".join(names) + ")"
        lines.append("  %s-%s  %-28s %s" % (s, e, what, ", ".join(rel.split("/", 1)[1] for rel in sorted(r["files"]))))
    return "\n".join(lines) + "\n"
