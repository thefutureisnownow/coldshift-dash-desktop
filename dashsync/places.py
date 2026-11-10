"""The app's Home, Work, saved places and recent destinations: back them up here, put them back.

The app keeps places.json in its own folder on the card (Android 4.4 lets it write nowhere else there):
    <card>/Android/data/racing.coldshift.dash/files/places.json
Backing up copies it to <workspace>/places.json, keeping the copy it replaces as places.previous.json.
Restoring writes the workspace's copy to <card>/coldshift.dash/places.json and tells the app, which
merges it into its own (the backup's Home and Work win; saved and recent places are added unless the
app has one within 30 m). The app merges each version of that file once, so it can stay on the card.

    {"version": 1, "places": [{"kind": "home"|"work"|"saved"|"recent", "name", "sub", "lat", "lon",
                              "time": ms since 1970}, ...]}
"""
import json
import os
import shutil
import tempfile

from . import layout

PHONE = layout.APP_DATA + "/places.json"
RESTORE = layout.APP_DIR + "/places.json"
KINDS = ("home", "work", "saved", "recent")


def read(path):
    """The places in a places.json, checked; raises ValueError for anything else."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    places = data.get("places") if isinstance(data, dict) else None
    if not isinstance(places, list):
        raise ValueError("%s is not a places file" % os.path.basename(path))
    for p in places:
        if p.get("kind") not in KINDS or not isinstance(p.get("lat"), (int, float)) or not isinstance(p.get("lon"), (int, float)):
            raise ValueError("%s has a place it cannot use: %r" % (os.path.basename(path), p))
    return places


def summary(places):
    """{"home": name or None, "work": ..., "saved": n, "recent": n}"""
    out = {"home": None, "work": None, "saved": 0, "recent": 0}
    for p in places:
        if p["kind"] in ("home", "work"):
            out[p["kind"]] = p.get("sub") or "%.5f, %.5f" % (p["lat"], p["lon"])
        else:
            out[p["kind"]] += 1
    return out


def describe(places):
    s = summary(places)
    parts = [("Home" if s["home"] else "no Home"), ("Work" if s["work"] else "no Work"),
             "%d saved" % s["saved"], "%d recent" % s["recent"]]
    return ", ".join(parts)


def backup_path(workspace):
    return os.path.join(workspace, "places.json")


def on_phone(target):
    """The phone's places (from its card copy), or None when it has none yet."""
    phone = layout.on_phone(target, PHONE)
    if not target.exists(phone):
        return None
    tmp = tempfile.mkdtemp()
    try:
        local = os.path.join(tmp, "places.json")
        target.pull(phone, local)
        return read(local)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def backup(target, workspace):
    """Copies the phone's places into the workspace. Returns {"places", "changed", "path"}; places is
    None when the phone has no places file yet."""
    os.makedirs(workspace, exist_ok=True)
    dest = backup_path(workspace)
    phone = layout.on_phone(target, PHONE)
    if not target.exists(phone):
        return {"places": None, "changed": False, "path": dest}
    tmp = dest + ".part"
    target.pull(phone, tmp)
    try:
        places = read(tmp)
    except ValueError:
        os.remove(tmp)
        raise
    with open(tmp, "rb") as f:
        new = f.read()
    old = None
    if os.path.exists(dest):
        with open(dest, "rb") as f:
            old = f.read()
    # places added here and not yet synced to the card stay (the phone does not have them yet)
    waiting = [p for p in (read(dest) if os.path.exists(dest) else []) if p.get("waiting")
               and not any(_near(p, q) for q in places)]
    if waiting:
        mine = {p["kind"] for p in waiting} & {"home", "work"}     # a Home or Work set here replaces the phone's
        places = [p for p in places if p["kind"] not in mine] + waiting
        new = _encode(places)
        with open(tmp, "wb") as f:
            f.write(new)
    if old == new:
        os.remove(tmp)
        return {"places": places, "changed": False, "path": dest}
    if old is not None:
        os.replace(dest, os.path.join(workspace, "places.previous.json"))
    os.replace(tmp, dest)
    return {"places": places, "changed": True, "path": dest}


def restore(target, workspace):
    """Puts the vehicle's places on the card for the app to merge in (it keeps its own and adds these;
    their Home and Work replace the phone's). Places added here stop waiting. Returns {"places", "app"}."""
    src = backup_path(workspace)
    if not os.path.exists(src):
        raise SystemExit("no places for this vehicle yet: copy them from the phone or add one first")
    places = read(src)
    target.push(src, RESTORE)
    reply = target.notify_synced(["places"])
    if any(p.get("waiting") for p in places):
        for p in places:
            p.pop("waiting", None)
        _write(workspace, places)
    return {"places": places, "app": reply}


# ---- adding places here ----

def _near(a, b, metres=30):
    import math
    dy = (a["lat"] - b["lat"]) * 111195
    dx = (a["lon"] - b["lon"]) * 111195 * math.cos(math.radians(a["lat"]))
    return a["kind"] == b["kind"] and math.hypot(dx, dy) < metres


def _encode(places):
    return json.dumps({"version": 1, "places": places}, indent=1, ensure_ascii=False).encode("utf-8")


def _write(workspace, places):
    dest = backup_path(workspace)
    with open(dest + ".part", "wb") as f:
        f.write(_encode(places))
    os.replace(dest + ".part", dest)


def parse_coords(text):
    """(lat, lon) from what people paste: "-33.92490, 18.42410", "-33.92490 18.42410", or
    "33.92490 S, 18.42410 E". Raises ValueError otherwise."""
    import re
    t = text.strip().upper().replace("\u00b0", " ")
    m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\s*([NS])?\s*[,; ]\s*([-+]?\d+(?:\.\d+)?)\s*([EW])?\s*$", t)
    if not m:
        raise ValueError("type the coordinates as latitude, longitude, e.g. -33.92490, 18.42410")
    lat, lon = float(m.group(1)), float(m.group(3))
    if m.group(2) == "S":
        lat = -abs(lat)
    if m.group(4) == "W":
        lon = -abs(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("latitude goes from -90 to 90 and longitude from -180 to 180")
    return lat, lon


def add(workspace, kind, name, lat, lon, sub=""):
    """Adds a place to the vehicle's places (Home and Work replace the old ones), waiting until it is
    synced to the card. Returns the places."""
    if kind not in ("home", "work", "saved"):
        raise ValueError("a place is home, work or saved")
    name = (name or "").strip() or {"home": "Home", "work": "Work"}.get(kind, "")
    if not name:
        raise ValueError("give the place a name")
    path = backup_path(workspace)
    places = read(path) if os.path.exists(path) else []
    if kind in ("home", "work"):
        places = [p for p in places if p["kind"] != kind]
    import time
    places.append({"kind": kind, "name": name, "sub": sub or "", "lat": round(lat, 6), "lon": round(lon, 6),
                   "time": int(time.time() * 1000), "waiting": True})
    os.makedirs(workspace, exist_ok=True)
    _write(workspace, places)
    return places


def remove(workspace, index):
    """Takes a place off this computer's list. The phone keeps its own copy (a sync to the card adds,
    it never removes): remove it on the phone too, in Go to."""
    path = backup_path(workspace)
    places = read(path)
    del places[index]
    _write(workspace, places)
    return places
