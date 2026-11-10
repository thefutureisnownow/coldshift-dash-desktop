"""BRouter routing tiles for offline navigation: which ones the region needs, download, card.

Source: https://brouter.de/brouter/segments4/<E|W><lon>_<N|S><lat>.rd5, one per 5 degree square
named by its south-west corner (E20_S35 covers 20..25 E, 35..30 S), from OpenStreetMap data (ODbL),
rebuilt daily. The tiles for the chosen map region are the squares its bounding box (from the map
file's header) touches; squares with no roads (open sea) have no tile and are skipped.

The app's RouterService reads them from <card>/coldshift.dash/routing/.
"""
import datetime
import email.utils
import json
import math
import os
import re
import struct
import urllib.request

from . import layout, maps
from .paths import cache_dir

BASE = "https://brouter.de/brouter/segments4/"
ROUTING_DIR = layout.APP_DIR + "/routing"
# Tiles are rebuilt every day, but roads change slowly: refresh a tile only when the server's is
# this much newer than ours, so a sync does not fetch the whole region again each day.
REFRESH = datetime.timedelta(days=30)
_ROW = re.compile(r'<a href="([EW]\d+_[NS]\d+\.rd5)">[^<]*</a>\s*(\d{2}-\w{3}-\d{4} \d{2}:\d{2})\s+(\d+)')


def tile_name(lat, lon):
    """The tile holding a point: E20_S35 for (-34.03, 23.05)."""
    lo, la = int(math.floor(lon / 5.0)) * 5, int(math.floor(lat / 5.0)) * 5
    return "%s%d_%s%d" % ("E" if lo >= 0 else "W", abs(lo), "N" if la >= 0 else "S", abs(la))


def tiles_for_bbox(min_lat, min_lon, max_lat, max_lon):
    names = []
    for la in range(int(math.floor(min_lat / 5.0)) * 5, int(math.floor(max_lat / 5.0)) * 5 + 1, 5):
        for lo in range(int(math.floor(min_lon / 5.0)) * 5, int(math.floor(max_lon / 5.0)) * 5 + 1, 5):
            names.append(tile_name(la, lo))
    return names


def map_bbox(path):
    """(min_lat, min_lon, max_lat, max_lon) from a Mapsforge map's header (microdegrees after the date)."""
    with open(path, "rb") as f:
        head = f.read(60)
    if not head.startswith(maps.MAGIC):
        raise ValueError("%s is not a Mapsforge map file" % os.path.basename(path))
    return tuple(v / 1e6 for v in struct.unpack(">iiii", head[44:60]))


def server_tiles():
    """{name: {"bytes", "modified"}} for every tile on the server."""
    with maps._get(BASE) as r:
        page = r.read().decode("utf-8", "replace")
    out = {}
    for name, when, size in _ROW.findall(page):
        out[name[:-4]] = {"bytes": int(size),
                          "modified": datetime.datetime.strptime(when, "%d-%b-%Y %H:%M").replace(tzinfo=datetime.timezone.utc)}
    return out


def wanted(region=None, available=None):
    """[(name, server info)] for the tiles the chosen region needs, from its cached map file."""
    region = region or maps.chosen()
    if not region:
        raise SystemExit("no region chosen yet: run  maps choose")
    local = maps.cached(region)
    if not local:
        raise SystemExit("the region's map is not downloaded yet: run  maps sync  (or maps get)")
    available = server_tiles() if available is None else available
    return [(n, available[n]) for n in tiles_for_bbox(*map_bbox(local)) if n in available]


def _tile_dir():
    d = os.path.join(cache_dir(), "routing")
    os.makedirs(d, exist_ok=True)
    return d


def _meta_path(name):
    return os.path.join(_tile_dir(), name + ".json")


def cached(name, info):
    """The cache copy of a tile if it is complete and recent enough, else None."""
    path = os.path.join(_tile_dir(), name + ".rd5")
    try:
        with open(_meta_path(name), encoding="utf-8") as f:
            meta = json.load(f)
        built = datetime.datetime.fromisoformat(meta["modified"])
    except (OSError, ValueError, KeyError):
        return None
    if not os.path.exists(path) or os.path.getsize(path) != meta.get("bytes"):
        return None
    if info and info["modified"] - built > REFRESH:
        return None
    return path


def download(name, info, progress=None):
    """Fetches one tile into the cache (checked against the size the server lists)."""
    have = cached(name, info)
    if have:
        return have
    path = os.path.join(_tile_dir(), name + ".rd5")
    part = path + ".part"
    resp = maps._get(BASE + name + ".rd5")
    total = int(resp.headers.get("Content-Length", info["bytes"]))
    done = 0
    with open(part, "wb") as f:
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if os.path.getsize(part) != info["bytes"]:
        os.remove(part)
        raise RuntimeError("%s.rd5 is incomplete: the server lists %d bytes" % (name, info["bytes"]))
    os.replace(part, path)
    mod = resp.headers.get("Last-Modified")
    built = email.utils.parsedate_to_datetime(mod) if mod else info["modified"]
    with open(_meta_path(name), "w", encoding="utf-8") as f:
        json.dump({"bytes": info["bytes"], "modified": built.isoformat()}, f)
    return path


def installed(target):
    return [e for e in target.listdir(ROUTING_DIR) if e.name.endswith(".rd5")]


def sync(target, progress=None, copying=None, region=None):
    """Puts the region's routing tiles on the card: downloads the missing (or much older) ones, copies
    those the card lacks or has at a different size, and removes tiles the region does not need.
    `progress(i, n, done, total, name)` while downloading. Returns a summary dict."""
    want = wanted(region)
    out = {"tiles": len(want), "downloaded": 0, "copied": 0, "removed": 0, "bytes": sum(i["bytes"] for _, i in want)}
    local = []
    for i, (name, info) in enumerate(want):
        fresh = cached(name, info) is None
        path = download(name, info, (lambda d, t, i=i, name=name: progress(i + 1, len(want), d, t, name)) if progress else None)
        out["downloaded"] += fresh
        local.append((name, path))
    if copying:
        copying()
    on_card = {e.name: e.size for e in installed(target)}
    for name, path in local:
        size = os.path.getsize(path)
        if on_card.get(name + ".rd5") != size:
            target.push(path, ROUTING_DIR + "/" + name + ".rd5")
            got = [e for e in installed(target) if e.name == name + ".rd5"]
            if not got or got[0].size != size:
                raise RuntimeError("copy failed: %s.rd5 on the card has the wrong size" % name)
            out["copied"] += 1
    keep = {name + ".rd5" for name, _ in local}
    for name in on_card:
        if name not in keep:
            target.remove(ROUTING_DIR + "/" + name)
            out["removed"] += 1
    return out
