"""Mapsforge map files: browse the download server, download with resume, check, install.

Source: https://download.mapsforge.org/maps/v5/<region>/<name>.map (OpenStreetMap data, ODbL).
The server gives sizes but no checksums, so a download is checked against the total file size
stored inside the map's own header.

The user picks one region (`choose`), which is remembered; `sync` keeps the cache and the card on
that region and fetches it again when the server has a newer build. A map's header records when it
was written, and the server's Last-Modified is within minutes of that, so the two are compared.
"""
import datetime
import email.utils
import html
import json
import os
import re
import http.client
import struct
import time
import urllib.error
import urllib.request

from . import paths
from .paths import cache_dir

BASE = "https://download.mapsforge.org/maps/v5/"
MAGIC = b"mapsforge binary OSM"
_ROW = re.compile(r'<a href="([^"?][^"]*)">[^<]*</a>\s*</td><td align="right">[^<]*</td><td align="right">\s*([^<]*?)\s*</td>')


def _get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "coldshift.dash-sync"})
    return urllib.request.urlopen(req, timeout=timeout)


def _human_to_bytes(s):
    s = s.strip()
    if not s or s == "-":
        return 0
    m = re.match(r"([\d.]+)\s*([KMG]?)", s)
    return int(float(m.group(1)) * {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}[m.group(2)]) if m else 0


def list_region(path=""):
    """Entries under a server folder: [{"name", "path", "dir", "approx_bytes"}]."""
    url = BASE + path.strip("/") + ("/" if path.strip("/") else "")
    page = _get(url).read().decode("utf-8", "replace")
    out = []
    for href, size in _ROW.findall(page):
        href = html.unescape(href)
        if href.startswith("/") or href.startswith("http") or href.startswith(".."):
            continue
        is_dir = href.endswith("/")
        if not is_dir and not href.endswith(".map"):
            continue
        out.append({"name": href.rstrip("/"), "path": (path.strip("/") + "/" if path.strip("/") else "") + href.rstrip("/"),
                    "dir": is_dir, "approx_bytes": _human_to_bytes(size)})
    return out


CATALOG_DAYS = 7


def catalog(refresh=False):
    """Every map on the server as [{"name", "path", "dir": False, "approx_bytes"}], crawled once and
    kept in the cache for CATALOG_DAYS (a full crawl is about 300 folder pages)."""
    from concurrent.futures import ThreadPoolExecutor
    cache = os.path.join(cache_dir(), "catalog.json")
    if not refresh:
        try:
            with open(cache, encoding="utf-8") as f:
                saved = json.load(f)
            age = datetime.datetime.now(datetime.timezone.utc).timestamp() - saved["fetched"]
            if age < CATALOG_DAYS * 86400:
                return saved["maps"]
        except (OSError, ValueError, KeyError):
            pass
    maps, folders = [], [""]
    with ThreadPoolExecutor(8) as pool:
        while folders:
            pages = list(pool.map(lambda d: _safe_list(d), folders))
            folders = []
            for entries in pages:
                for e in entries:
                    (folders if e["dir"] else maps).append(e["path"] if e["dir"] else e)
    maps.sort(key=lambda e: e["path"])
    tmp = cache + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"fetched": datetime.datetime.now(datetime.timezone.utc).timestamp(), "maps": maps}, f)
    os.replace(tmp, cache)
    return maps


def _safe_list(path):
    try:
        return list_region(path)
    except Exception:
        return []


def _words(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).split()


def find(term, refresh=False):
    """Maps matching every word of `term` ("south africa" finds south-africa-and-lesotho), with maps
    whose file name matches on its own first; "africa" still lists every map in the africa folder."""
    want = _words(term)

    def hit(text):
        return all(w in text for w in want)

    every = [e for e in catalog(refresh) if hit(e["path"].lower())]
    return sorted(every, key=lambda e: not hit(e["name"].lower()))


def best(hits, term):
    """The one map whose file name matches `term` by itself, or None."""
    want = _words(term)
    named = [e for e in hits if all(w in e["name"].lower() for w in want)]
    return named[0] if len(named) == 1 else None


def header_date(path):
    """When the map was written (UTC), from its header, or None if it is not a map file."""
    with open(path, "rb") as f:
        head = f.read(44)
    if len(head) < 44 or not head.startswith(MAGIC):
        return None
    ms = struct.unpack(">q", head[36:44])[0]
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)


def remote_info(path):
    """{"bytes", "modified"} for a map on the server; raises if it is not there."""
    req = urllib.request.Request(BASE + path, method="HEAD", headers={"User-Agent": "coldshift.dash-sync"})
    with urllib.request.urlopen(req, timeout=30) as r:
        mod = r.headers.get("Last-Modified")
        return {"bytes": int(r.headers.get("Content-Length", 0)),
                "modified": email.utils.parsedate_to_datetime(mod) if mod else None}


# A server build counts as newer than the cached copy only if it is this much younger than the
# copy's header date (the server stamps the file a few minutes after the writer finishes).
NEWER = datetime.timedelta(hours=12)


def is_newer(remote, local_path):
    local = header_date(local_path)
    return bool(remote and remote.get("modified") and local and remote["modified"] - local > NEWER)


def header_size(path):
    """The total file size a map claims in its header, or None if it is not a map file."""
    with open(path, "rb") as f:
        head = f.read(40)
    if len(head) < 36 or not head.startswith(MAGIC):
        return None
    return struct.unpack(">q", head[28:36])[0]


def check(path):
    """Raises ValueError unless `path` is a complete map file."""
    claimed = header_size(path)
    if claimed is None:
        raise ValueError("%s is not a Mapsforge map file" % os.path.basename(path))
    if claimed != os.path.getsize(path):
        raise ValueError("%s is incomplete: header says %d bytes, file has %d"
                         % (os.path.basename(path), claimed, os.path.getsize(path)))
    return claimed


def cached(path):
    """The checked cache copy of a server map, or None."""
    final = os.path.join(cache_dir(), os.path.basename(path))
    try:
        check(final)
        return final
    except (OSError, ValueError):
        return None


RETRIES = 4     # more tries after a connection drops or stalls; each carries on where the last stopped


def download(path, progress=None, remote=None, pause=2.0):
    """Downloads a map (resuming a partial one) into the cache and returns its local path.
    With `remote` (from remote_info), a cached copy older than the server's is fetched again; the old
    copy stays in use until the new one is complete and checked. The server stalls now and then on a
    file this size: a dropped or timed-out connection is tried again RETRIES times, resuming."""
    for attempt in range(RETRIES + 1):
        try:
            return _download(path, progress, remote)
        except urllib.error.HTTPError:
            raise                                   # the server answered: asking again changes nothing
        except (TimeoutError, ConnectionError, urllib.error.URLError, http.client.HTTPException):
            if attempt == RETRIES:
                raise
            time.sleep(pause * (attempt + 1))


def _download(path, progress, remote):
    name = os.path.basename(path)
    final = os.path.join(cache_dir(), name)
    have_final = cached(path)
    if have_final and not is_newer(remote, have_final):
        return final
    if os.path.exists(final) and not have_final:
        os.remove(final)
    part = final + ".part"
    meta = part + ".json"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    url = BASE + path
    headers = {"User-Agent": "coldshift.dash-sync"}
    if have:
        headers["Range"] = "bytes=%d-" % have
        try:
            with open(meta, encoding="utf-8") as f:
                headers["If-Range"] = json.load(f)["last_modified"]
        except (OSError, ValueError, KeyError):
            have, headers = 0, {"User-Agent": "coldshift.dash-sync"}   # cannot tell if the server file changed
    resp = _get(url, headers)
    if have and resp.status != 206:
        have = 0          # the server sent the whole (possibly newer) file
    if resp.headers.get("Last-Modified"):
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({"last_modified": resp.headers["Last-Modified"]}, f)
    total = have + int(resp.headers.get("Content-Length", 0))
    with open(part, "ab" if have else "wb") as f:
        done = have
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    check(part)
    os.replace(part, final)
    if os.path.exists(meta):
        os.remove(meta)
    return final


def chosen():
    """The region the user picked, as a server path (e.g. africa/south-africa-and-lesotho.map), or None."""
    return paths.load_config().get("map_region")


def choose(path):
    """Remembers `path` as the region after checking the server has it. Returns remote_info."""
    path = path.strip("/")
    if not path.endswith(".map"):
        path += ".map"
    info = remote_info(path)
    cfg = paths.load_config()
    cfg["map_region"] = path
    paths.save_config(cfg)
    return path, info


def status(target=None, maps_dir=None):
    """Where the chosen region stands: on the server, in the cache, on the card."""
    region = chosen()
    out = {"region": region, "server": None, "cache": None, "card": None, "card_other": []}
    if not region:
        return out
    try:
        out["server"] = remote_info(region)
    except Exception as e:
        out["server_error"] = str(e)
    local = cached(region)
    if local:
        out["cache"] = {"path": local, "bytes": os.path.getsize(local), "written": header_date(local),
                        "outdated": is_newer(out["server"], local)}
    if target is not None:
        name = os.path.basename(region)
        for e in installed(target, maps_dir):
            if e.name == name:
                out["card"] = {"bytes": e.size, "current": bool(local) and e.size == os.path.getsize(local)}
            else:
                out["card_other"].append(e.name)
    return out


def sync(target, maps_dir, progress=None, copying=None):
    """Makes the card hold exactly the chosen region, fetching a newer build first if there is one.
    The app shows one map, so other maps on the card are removed once the new one is in place.
    `copying()` is called when the download is done and the copy to the card starts."""
    region = chosen()
    if not region:
        raise SystemExit("no region chosen yet: run  maps choose")
    local = download(region, progress, remote_info(region))
    if copying:
        copying()
    return install(target, local, maps_dir, replace=True, replace_older=True)


def tell_app(target, result):
    """After a copy that changed the card, asks the running app to reload its map. Returns a note for
    the user, or "" if there is nothing to say."""
    if result == "already installed":
        return ""
    reply = target.notify_synced(["maps"])
    if reply:
        return "the app " + reply
    return "" if target.kind != "adb" else "the app is not running; it shows the new map when it starts"


def installed(target, maps_dir):
    return [e for e in target.listdir(maps_dir) if e.name.endswith(".map")]


def install(target, local, maps_dir, replace=False, replace_older=False):
    """Copies a checked map onto the card. The app uses the first .map in the folder, so a different
    map already there is only removed with replace=True. A copy with the same name but a different
    size (an older build) counts as different too. Returns a short description of what it did."""
    check(local)
    name = os.path.basename(local)
    size = os.path.getsize(local)
    existing = installed(target, maps_dir)
    same = [e for e in existing if e.name == name and e.size == size]
    others = [e for e in existing if e not in same]
    stale = [e for e in others if e.name == name]
    if stale and not replace_older:
        raise SystemExit("the card has a different %s (%d bytes); run again with --replace to update it"
                         % (name, stale[0].size))
    others = [e for e in others if e.name != name]    # the push replaces a same-name copy in one rename
    if same and not others:
        return "already installed"
    if others and not replace:
        raise SystemExit("the card already has %s; the app uses one map, so run again with --replace to swap it"
                         % ", ".join(e.name for e in others))
    free = target.free_bytes()
    if free is not None and free < size + 50 * 1024 * 1024:
        raise SystemExit("not enough space on the card")
    if not same:
        target.push(local, maps_dir + "/" + name)
    got = [e for e in installed(target, maps_dir) if e.name == name]
    if not got or got[0].size != size:
        raise SystemExit("copy failed: size on the card does not match")
    for e in others:
        target.remove(maps_dir + "/" + e.name)
    what = "updated" if stale else "installed"
    return "%s %s%s" % (what, name, " (replaced %s)" % ", ".join(e.name for e in others) if others else "")
