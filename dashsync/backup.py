"""Backing up a vehicle's phone, and putting the whole vehicle on a phone.

Most of a vehicle lives here already (its music, map region, voices, look); what only the phone has is
what was set or recorded on it: places (Home, Work, saved, recent), the app's settings (brightness,
screen-off time, heading-up, voice), the log book and the track segments and runs. The app keeps them in
its folder on the card, and `backup` copies them into the vehicle's folder (places.json,
app-settings.json, the copy each replaces kept as *.previous.json; log/ and track/ as their Sync to PC).

`restore` puts everything on a phone, e.g. a new one: places and settings (the app takes them in), the
log book and track segments, the look, the voices, the map with its routing tiles and place search, and
the music.
"""
import os

from . import layout, logbook, maps, mirror, places, profile, routing, search, track, voice

SETTINGS_PHONE = layout.APP_DATA + "/settings.json"
SETTINGS_RESTORE = layout.APP_DIR + "/settings.json"
SETTINGS_FILE = "app-settings.json"


def _keep(new, dest):
    """Replaces dest with new unless they are the same; the old copy becomes *.previous.json."""
    with open(new, "rb") as f:
        data = f.read()
    if os.path.exists(dest):
        with open(dest, "rb") as f:
            if f.read() == data:
                os.remove(new)
                return False
        os.replace(dest, dest[:-5] + ".previous.json")
    os.replace(new, dest)
    return True


def backup(target, vehicle):
    """Copies the phone's places, settings, log book and track into the vehicle. Returns {"places",
    "settings", "changed"}: places as read (None when the phone has none yet), settings as a dict (None
    likewise), and what changed."""
    import json
    out = {"places": None, "settings": None, "changed": []}
    r = places.backup(target, vehicle)
    out["places"] = r["places"]
    if r["changed"]:
        out["changed"].append("places")
    settings_phone = layout.on_phone(target, SETTINGS_PHONE)
    if target.exists(settings_phone):
        dest = os.path.join(vehicle, SETTINGS_FILE)
        tmp = dest + ".part"                  # beside it: a rename across disks fails
        try:
            target.pull(settings_phone, tmp)
            with open(tmp, encoding="utf-8") as f:
                out["settings"] = json.load(f)
            if _keep(tmp, dest):
                out["changed"].append("settings")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    r = logbook.sync_to_pc(target, vehicle)
    if r["new"] or r["updated"]:
        out["changed"].append("log book")
    r = track.sync_to_pc(target, vehicle)
    if r["segments"] or r["runs"]:
        out["changed"].append("track")
    return out


def saved(vehicle):
    """What a restore would put back from the backup: {"places": [...] or None, "settings": {...} or None}."""
    import json
    out = {"places": None, "settings": None}
    p = places.backup_path(vehicle)
    if os.path.exists(p):
        out["places"] = places.read(p)
    s = os.path.join(vehicle, SETTINGS_FILE)
    if os.path.exists(s):
        with open(s, encoding="utf-8") as f:
            out["settings"] = json.load(f)
    return out


STEPS = ("places and settings", "log book and track", "look", "voices", "map", "routing", "place search", "music")


def restore(target, vehicle, step=None, progress=None, copying=None):
    """Puts the whole vehicle on the phone or card. `step(name)` as each part starts, `progress(done,
    total)` during downloads and copies, `copying()` when a part's download is done and its copy to the
    phone starts. Returns {part: short description}."""
    out = {}

    def begin(name):
        if step:
            step(name)

    begin("places and settings")
    told = []
    if os.path.exists(places.backup_path(vehicle)):
        target.push(places.backup_path(vehicle), places.RESTORE)
        told.append("places")
    if os.path.exists(os.path.join(vehicle, SETTINGS_FILE)):
        target.push(os.path.join(vehicle, SETTINGS_FILE), SETTINGS_RESTORE)
        told.append("settings")
    out["places and settings"] = ", ".join(told) or "none backed up yet"
    begin("log book and track")
    n = logbook.restore(target, vehicle)
    s = track.sync_to_card(target, vehicle)["segments"]
    out["log book and track"] = "%d log book entries, %d segments" % (n, s)
    begin("look")
    r = profile.sync(target, vehicle)
    out["look"] = "updated" if r["changed"] else "already there"
    begin("voices")
    r = voice.sync(target, vehicle)
    out["voices"] = ", ".join(r["packs"]) or "only the built-in one"
    if maps.chosen():
        begin("map")
        r = maps.sync(target, layout.MAPS_DIR, progress, copying)
        out["map"] = r
        begin("routing")
        r = routing.sync(target, (lambda i, n, d, t, name: progress(d, t)) if progress else None, copying)
        out["routing"] = "%d tiles, %d copied" % (r["tiles"], r["copied"])
        begin("place search")
        r = search.sync(target, progress, copying, log=lambda line: None)
        out["place search"] = "copied" if r["copied"] else "already there"
    else:
        out["map"] = "no region chosen yet"
    begin("music")
    music = os.path.join(vehicle, *layout.MUSIC_DIR.split("/"))
    if os.path.isdir(music):
        r = mirror.push_music(target, vehicle, progress=(lambda i, n, d, t, name: progress(i, n)) if progress else None)
        out["music"] = "%d files copied" % len(r["music"]["copy"])
    else:
        out["music"] = "none in this vehicle"
    out["app"] = target.notify_synced(["places", "settings", "log", "track", "profile", "voice", "maps", "search", "music"])
    return out
