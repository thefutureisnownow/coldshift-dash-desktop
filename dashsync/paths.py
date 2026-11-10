"""Where the tool keeps its settings, downloads and cache, per operating system.

DASHSYNC_CONFIG and DASHSYNC_CACHE override the two folders (used by tests and for portable installs).
"""
import json
import os
import sys

APP = "coldshift.dash"


def app_assets(*parts):
    """A folder of the car app's assets this tool shows (brand, built-in profile, voice pack): from the
    repository's assets/ (copies of the app's), or from inside the packaged app."""
    if getattr(sys, "frozen", False):
        base = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "assets")
    else:
        base = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "assets"))
    return os.path.join(base, *parts)


def config_dir():
    d = os.environ.get("DASHSYNC_CONFIG")
    if not d:
        if sys.platform == "darwin":
            d = os.path.expanduser("~/Library/Application Support/" + APP)
        elif os.name == "nt":
            d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP)
        else:
            d = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), APP)
    os.makedirs(d, exist_ok=True)
    return d


def cache_dir():
    d = os.environ.get("DASHSYNC_CACHE")
    if not d:
        if sys.platform == "darwin":
            d = os.path.expanduser("~/Library/Caches/" + APP)
        elif os.name == "nt":
            d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP, "cache")
        else:
            d = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), APP)
    os.makedirs(d, exist_ok=True)
    return d


def log_file():
    """Where the packaged app writes what would go to a terminal (it has none): errors, for support."""
    return os.path.join(config_dir(), "log.txt")


def tools_dir():
    """Programs the tool downloaded for itself (adb). Not the cache: clearing the cache must not remove them."""
    d = os.path.join(config_dir(), "tools")
    os.makedirs(d, exist_ok=True)
    return d


# Settings that belong to a vehicle, kept in its folder's vehicle.json; everything else is global.
VEHICLE_KEYS = ("name", "map_region", "phone", "card", "recordings")
VEHICLE_FILE = "vehicle.json"


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
    except PermissionError:
        # seen after running the tool once with sudo: the folder then belongs to root
        raise SystemExit("cannot save settings in %s (no write permission). If it was created by running "
                         "the tool as root, give it back with:  sudo chown -R \"$USER\" \"%s\""
                         % (os.path.dirname(path), os.path.dirname(path)))
    os.replace(tmp, path)


def global_config():
    """The settings file itself: {"vehicles": [{"id", "folder"}], "vehicle": id, "adb": ...}."""
    cfg = _read(os.path.join(config_dir(), "config.json"))
    if cfg.get("workspace") and "vehicles" not in cfg:
        cfg = _migrate(cfg)
    return cfg


def save_global(cfg):
    _write(os.path.join(config_dir(), "config.json"), cfg)


def _migrate(cfg):
    """Settings from before vehicles: the workspace becomes the first vehicle, where it is."""
    folder = cfg.pop("workspace")
    v = _read(os.path.join(folder, VEHICLE_FILE))
    for k in VEHICLE_KEYS:
        if k in cfg:
            v.setdefault(k, cfg.pop(k))
    v.setdefault("name", "My car")
    v.setdefault("id", "my-car")
    v.setdefault("version", 1)
    os.makedirs(folder, exist_ok=True)
    _write(os.path.join(folder, VEHICLE_FILE), v)
    cfg["vehicles"] = [{"id": v["id"], "folder": folder}]
    cfg["vehicle"] = v["id"]
    save_global(cfg)
    return cfg


def current_vehicle(cfg=None):
    """The open vehicle's {"id", "folder"}, or None."""
    cfg = cfg if cfg is not None else global_config()
    for v in cfg.get("vehicles", []):
        if v["id"] == cfg.get("vehicle"):
            return v
    return None


def load_config():
    """The global settings with the open vehicle's on top, and "workspace": its folder."""
    cfg = global_config()
    v = current_vehicle(cfg)
    if v:
        mine = _read(os.path.join(v["folder"], VEHICLE_FILE))
        cfg.update({k: mine[k] for k in VEHICLE_KEYS if k in mine})
        cfg["workspace"] = v["folder"]
    return cfg


def save_config(cfg):
    """Saves what load_config gave (changed): vehicle settings to the open vehicle, the rest globally.
    Without a vehicle (tests, first run) everything stays global."""
    cfg = dict(cfg)
    g = global_config()
    v = current_vehicle(g)
    if v:
        path = os.path.join(v["folder"], VEHICLE_FILE)
        mine = _read(path)
        for k in VEHICLE_KEYS:
            if cfg.get(k) is not None:
                mine[k] = cfg[k]
            else:
                mine.pop(k, None)
            cfg.pop(k, None)
        cfg.pop("workspace", None)
        _write(path, mine)
        cfg["vehicles"], cfg["vehicle"] = g["vehicles"], g["vehicle"]
    save_global(cfg)
