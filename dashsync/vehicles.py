"""Vehicles: everything the tool keeps is per vehicle, in that vehicle's folder (once called the
workspace): its music, voice packs, profile (the look), places, map region, and which phone or card it
uses (vehicle.json). The settings file lists the vehicles and which one is open.

    <folder>/vehicle.json   {"version": 1, "id", "name", "map_region", "phone", "card", "recordings"}
    <folder>/Music/ ...      as before
"""
import os
import re

from . import paths


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "vehicle"


def info(entry):
    """{"id", "name", "folder", "exists"} for a settings entry."""
    v = paths._read(os.path.join(entry["folder"], paths.VEHICLE_FILE))
    return {"id": entry["id"], "folder": entry["folder"], "name": v.get("name") or entry["id"],
            "exists": os.path.isdir(entry["folder"])}


def all():
    return [info(e) for e in paths.global_config().get("vehicles", [])]


def current():
    v = paths.current_vehicle()
    return info(v) if v else None


def default_folder(name):
    """Beside the open vehicle's folder, else in Documents."""
    cur = paths.current_vehicle()
    base = os.path.dirname(cur["folder"]) if cur else os.path.join(os.path.expanduser("~"), "Documents", "coldshift.dash")
    return os.path.join(base, slug(name))


def _register(vid, folder, select=True):
    cfg = paths.global_config()
    cfg.setdefault("vehicles", [])
    cfg["vehicles"] = [e for e in cfg["vehicles"] if e["id"] != vid] + [{"id": vid, "folder": folder}]
    if select:
        cfg["vehicle"] = vid
    paths.save_global(cfg)


def _free_id(name):
    taken = {e["id"] for e in paths.global_config().get("vehicles", [])}
    base = slug(name)
    vid, n = base, 2
    while vid in taken:
        vid, n = "%s-%d" % (base, n), n + 1
    return vid


def create(name, folder=None):
    """A new vehicle in a new (or empty) folder, opened. Returns its info."""
    name = name.strip()
    if not name:
        raise ValueError("give the vehicle a name")
    folder = os.path.abspath(os.path.expanduser(folder or default_folder(name)))
    if os.path.exists(os.path.join(folder, paths.VEHICLE_FILE)):
        raise ValueError("%s already holds a vehicle; use Add instead" % folder)
    os.makedirs(folder, exist_ok=True)
    vid = _free_id(name)
    paths._write(os.path.join(folder, paths.VEHICLE_FILE), {"version": 1, "id": vid, "name": name})
    _register(vid, folder)
    return current()


def add(folder):
    """An existing vehicle folder (or any folder, which becomes one), opened. Returns its info."""
    folder = os.path.abspath(os.path.expanduser(folder))
    if not os.path.isdir(folder):
        raise ValueError("no such folder: %s" % folder)
    for e in paths.global_config().get("vehicles", []):
        if os.path.abspath(e["folder"]) == folder:
            select(e["id"])
            return current()
    path = os.path.join(folder, paths.VEHICLE_FILE)
    v = paths._read(path)
    v.setdefault("version", 1)
    v.setdefault("name", os.path.basename(folder.rstrip(os.sep)) or "Vehicle")
    vid = v["id"] if v.get("id") and v["id"] not in {e["id"] for e in paths.global_config().get("vehicles", [])} \
        else _free_id(v["name"])
    v["id"] = vid
    paths._write(path, v)
    _register(vid, folder)
    return current()


def select(vid):
    cfg = paths.global_config()
    if not any(e["id"] == vid for e in cfg.get("vehicles", [])):
        raise ValueError("no vehicle %r" % vid)
    cfg["vehicle"] = vid
    paths.save_global(cfg)


def rename(vid, name):
    if not name.strip():
        raise ValueError("give the vehicle a name")
    for e in paths.global_config().get("vehicles", []):
        if e["id"] == vid:
            path = os.path.join(e["folder"], paths.VEHICLE_FILE)
            v = paths._read(path)
            v["name"] = name.strip()
            paths._write(path, v)
            return
    raise ValueError("no vehicle %r" % vid)


def forget(vid):
    """Takes a vehicle off the list; its folder stays."""
    cfg = paths.global_config()
    cfg["vehicles"] = [e for e in cfg.get("vehicles", []) if e["id"] != vid]
    if cfg.get("vehicle") == vid:
        cfg["vehicle"] = cfg["vehicles"][0]["id"] if cfg["vehicles"] else None
    paths.save_global(cfg)
