"""Offline place search for the app: an SQLite file built from OpenStreetMap data, put on the card.

Source: the Geofabrik extract with the same name as the map region (download.geofabrik.de, OpenStreetMap
data, ODbL), cached and fetched again when Geofabrik's is REFRESH newer. From it come towns and suburbs,
named streets (one row per street per area), named places (shops, fuel, schools, ...) and addresses
(house number and street). Each row gets an area ("Suburb, Town") from the nearest place nodes.

The app reads <card>/coldshift.dash/search/<region>.db. Android 4.4 ships SQLite 3.7.11, so the file
uses nothing newer: a plain table and a contentless FTS4 table with the simple tokenizer, which only
folds ASCII, so the words are folded to lower-case ASCII here and the app folds the query the same way.

    meta(key PRIMARY KEY, value)      version, region, source date
    place(id INTEGER PRIMARY KEY, kind, name, folded, detail, area, keys, lat, lon, rank)
                                      folded: the name as folded words; keys: " " + every word of the
                                      name, what it is and the area; lat/lon in microdegrees;
                                      rank: higher shows first
    words(head)                       FTS4, docid = place.id: the name and what it is ("fuel")

A search looks up its first word in `words` (so a town's name finds the town and places named after
it, not every street in it) and checks the other words against `keys` with LIKE: an FTS AND with a
short word like "st" makes the phone read that word's list for the whole country (over a second).
Of the matches, the app scores only the NEAR nearest and the BEST best-ranked, which SQLite picks.
"""
import datetime
import email.utils
import json
import math
import os
import re
import sqlite3
import unicodedata

from . import layout, maps, paths
from .paths import cache_dir

VERSION = 3
SEARCH_DIR = layout.APP_DIR + "/search"
GEOFABRIK = "https://download.geofabrik.de/"
INDEX_URL = GEOFABRIK + "index-v1-nogeom.json"
REFRESH = datetime.timedelta(days=30)
NEAR, BEST = 150, 150

# kinds, in the app's order of preference when the words match equally well
CITY, TOWN, VILLAGE, SUBURB, STREET, POI, ADDRESS = 1, 2, 3, 4, 5, 6, 7
KIND_RANK = {CITY: 90, TOWN: 80, VILLAGE: 60, SUBURB: 55, STREET: 40, POI: 45, ADDRESS: 30}

PLACES = {"city": CITY, "town": TOWN, "village": VILLAGE, "hamlet": VILLAGE, "suburb": SUBURB,
          "neighbourhood": SUBURB, "quarter": SUBURB, "borough": SUBURB}
ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
         "living_street", "pedestrian", "service", "motorway_link", "trunk_link", "primary_link",
         "secondary_link", "tertiary_link", "road"}
POI_KEYS = ("amenity", "shop", "tourism", "leisure", "office", "healthcare", "craft", "aeroway", "railway",
            "historic", "sport", "club")
# words shown under a place's name; values not listed are shown with "_" as a space
LABELS = {"fuel": "Fuel", "supermarket": "Supermarket", "restaurant": "Restaurant", "fast_food": "Fast food",
          "cafe": "Café", "pharmacy": "Pharmacy", "hospital": "Hospital", "clinic": "Clinic",
          "school": "School", "university": "University", "college": "College", "place_of_worship": "Church",
          "bank": "Bank", "atm": "ATM", "police": "Police", "parking": "Parking", "hotel": "Hotel",
          "guest_house": "Guest house", "mall": "Shopping centre", "car_repair": "Car repair", "car": "Car dealer",
          "tyres": "Tyres", "aerodrome": "Airport", "station": "Station", "park": "Park",
          "sports_centre": "Sports centre", "golf_course": "Golf course", "stadium": "Stadium"}
SKIP_POI = {"parking_space", "bench", "waste_basket", "vending_machine", "toilets", "post_box", "bicycle_parking",
            "grit_bin", "recycling", "drinking_water", "shelter", "hunting_stand", "picnic_table", "fire_hydrant"}
# extra words so "york st" finds York Street
ABBREV = {"street": "st", "road": "rd", "avenue": "ave", "drive": "dr", "crescent": "cres", "close": "cl",
          "lane": "ln", "place": "pl", "boulevard": "blvd", "highway": "hwy", "saint": "st", "mount": "mt",
          "straat": "str", "weg": "wg", "laan": "ln"}


def fold(s):
    """Lower-case ASCII words: "Église  St-Pierre" -> "eglise st pierre" (the app does the same)."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", s))


def keywords(*parts):
    words = []
    for p in parts:
        for w in fold(p or "").split():
            if w not in words:
                words.append(w)
            if w in ABBREV and ABBREV[w] not in words:
                words.append(ABBREV[w])
    return " ".join(words)


# ---- the source extract ----

def _index():
    path = os.path.join(cache_dir(), "geofabrik-index.json")
    try:
        if datetime.datetime.now().timestamp() - os.path.getmtime(path) < 7 * 86400:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    with maps._get(INDEX_URL) as r:
        data = json.loads(r.read().decode("utf-8"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def source_url(region=None):
    """Geofabrik's .osm.pbf for the region: the extract with the map file's name."""
    region = region or maps.chosen()
    if not region:
        raise SystemExit("no region chosen yet: run  maps choose")
    name = os.path.basename(region)[:-4]
    for f in _index()["features"]:
        p = f["properties"]
        if p["id"] == name and p.get("urls", {}).get("pbf"):
            return p["urls"]["pbf"]
    raise SystemExit("Geofabrik has no extract named %s, so there is no search data for this region" % name)


def _src_path(url):
    return os.path.join(cache_dir(), "osm", os.path.basename(url))


def source(url, progress=None):
    """The cached extract, downloading it when missing or when Geofabrik's is REFRESH newer."""
    path = _src_path(url)
    meta = path + ".json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    head = maps._get(url)
    remote = email.utils.parsedate_to_datetime(head.headers["Last-Modified"])
    total = int(head.headers.get("Content-Length", 0))
    try:
        with open(meta, encoding="utf-8") as f:
            have = json.load(f)
        if os.path.getsize(path) == have["bytes"] and remote - datetime.datetime.fromisoformat(have["modified"]) < REFRESH:
            head.close()
            return path, datetime.datetime.fromisoformat(have["modified"])
    except (OSError, ValueError, KeyError):
        pass
    part, done = path + ".part", 0
    with open(part, "wb") as f:
        while True:
            chunk = head.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    head.close()
    if total and os.path.getsize(part) != total:
        os.remove(part)
        raise RuntimeError("%s is incomplete" % os.path.basename(url))
    os.replace(part, path)
    with open(meta, "w", encoding="utf-8") as f:
        json.dump({"bytes": os.path.getsize(path), "modified": remote.isoformat()}, f)
    return path, remote


# ---- reading OSM ----

# for these keys only the listed values are places someone drives to (not every tram stop or taxiway)
ONLY = {"railway": {"station", "halt"}, "aeroway": {"aerodrome", "terminal", "heliport"}}


def _label(tags):
    for k in POI_KEYS:
        v = tags.get(k)
        if v and v not in ("yes", "no"):
            if v in SKIP_POI or (k in ONLY and v not in ONLY[k]):
                return None
            return LABELS.get(v, v.replace("_", " ").capitalize())
    return None


def read_osm(pbf):
    """Everything worth finding in the extract, as (places, streets, pois, addresses) lists of tuples."""
    import osmium

    places, streets, pois, addrs = [], [], [], []

    def centre(nodes):
        lat = lon = 0.0
        n = 0
        for nd in nodes:
            if nd.location.valid():
                lat += nd.location.lat
                lon += nd.location.lon
                n += 1
        return (lat / n, lon / n) if n else None

    fp = osmium.FileProcessor(pbf).with_locations().with_filter(
        osmium.filter.KeyFilter("name", "addr:housenumber", "place"))
    for o in fp:
        if o.is_relation():
            continue
        tags = o.tags
        name = tags.get("name")
        if o.is_node():
            if not o.location.valid():
                continue
            at = (o.location.lat, o.location.lon)
        else:
            nodes = o.nodes
            if len(nodes) < 2:
                continue
            closed = nodes[0].ref == nodes[-1].ref
            if not closed and "highway" in tags:
                mid = nodes[len(nodes) // 2]
                if not mid.location.valid():
                    continue
                at = (mid.location.lat, mid.location.lon)
            else:
                at = centre(nodes)
                if at is None:
                    continue
        place = tags.get("place")
        if name and o.is_node() and place in PLACES:
            pop = tags.get("population", "")
            places.append((PLACES[place], name, at[0], at[1], int(pop) if pop.isdigit() else 0))
            continue
        if name and o.is_way() and tags.get("highway") in ROADS:
            streets.append((name, at[0], at[1], tags.get("addr:suburb") or None))
            continue
        number, street = tags.get("addr:housenumber"), tags.get("addr:street")
        label = _label(tags) if name else None
        if name and label:
            pois.append((name, label, at[0], at[1], tags.get("addr:suburb") or tags.get("addr:city")))
        if number and street:
            addrs.append((number.strip(), street, at[0], at[1], tags.get("addr:suburb"), tags.get("addr:city")))
    return places, streets, pois, addrs


class Areas:
    """Names the area around a point from the place nodes: the nearest suburb or village, and town."""
    CELL = 0.1

    def __init__(self, places):
        self.small, self.big = {}, {}
        for kind, name, lat, lon, pop in places:
            grid = self.big if kind in (CITY, TOWN) else self.small
            grid.setdefault(self._cell(lat, lon), []).append((name, lat, lon, kind))

    def _cell(self, lat, lon):
        return int(math.floor(lat / self.CELL)), int(math.floor(lon / self.CELL))

    def _nearest(self, grid, lat, lon, reach, max_km):
        cy, cx = self._cell(lat, lon)
        best, best_d = None, max_km
        cos = math.cos(math.radians(lat))
        for y in range(cy - reach, cy + reach + 1):
            for x in range(cx - reach, cx + reach + 1):
                for name, plat, plon, kind in grid.get((y, x), ()):
                    d = math.hypot((plat - lat) * 111.2, (plon - lon) * 111.2 * cos)
                    if kind == CITY:
                        d *= 0.5          # cities reach further than towns
                    if d < best_d:
                        best, best_d = name, d
        return best

    def name(self, lat, lon, suburb=None, city=None):
        small = suburb or self._nearest(self.small, lat, lon, 1, 4.0)
        big = city or self._nearest(self.big, lat, lon, 2, 20.0)
        parts = [p for p in (small, big) if p]
        if len(parts) == 2 and fold(parts[0]) == fold(parts[1]):
            parts = parts[:1]
        return ", ".join(parts)


def _street_rank(name):
    return KIND_RANK[STREET]


def build(pbf, out, region="", source_date=None, log=print):
    """Writes the search database for an extract to `out` (replaced in one rename when done)."""
    places, streets, pois, addrs = read_osm(pbf)
    log("read %d places, %d street pieces, %d named places, %d addresses"
        % (len(places), len(streets), len(pois), len(addrs)))
    areas = Areas(places)
    rows = []
    for kind, name, lat, lon, pop in places:
        area = "" if kind in (CITY, TOWN) else areas.name(lat, lon)
        if fold(area).startswith(fold(name)):
            area = areas._nearest(areas.big, lat, lon, 2, 20.0) or ""
            if fold(area) == fold(name):
                area = ""
        rank = KIND_RANK[kind] + min(9, int(math.log10(pop + 1) * 1.5))
        rows.append((kind, name, "", area, lat, lon, rank))
    # one row per street name per area, at the piece nearest the middle of them
    grouped = {}
    for name, lat, lon, suburb in streets:
        area = areas.name(lat, lon, suburb)
        grouped.setdefault((name, area), []).append((lat, lon))
    for (name, area), pts in grouped.items():
        mlat = sum(p[0] for p in pts) / len(pts)
        mlon = sum(p[1] for p in pts) / len(pts)
        lat, lon = min(pts, key=lambda p: (p[0] - mlat) ** 2 + (p[1] - mlon) ** 2)
        rows.append((STREET, name, "", area, lat, lon, _street_rank(name)))
    seen = set()
    for name, label, lat, lon, suburb in pois:
        area = areas.name(lat, lon, suburb)
        if (name, label, area) in seen:       # a shop mapped as a point and as a building
            continue
        seen.add((name, label, area))
        rows.append((POI, name, label, area, lat, lon, KIND_RANK[POI]))
    seen = set()
    for number, street, lat, lon, suburb, city in addrs:
        area = areas.name(lat, lon, suburb, city)
        text = "%s %s" % (number, street)
        if (fold(text), area) in seen:
            continue
        seen.add((fold(text), area))
        rows.append((ADDRESS, text, "", area, lat, lon, KIND_RANK[ADDRESS]))

    tmp = out + ".part"
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    db.execute("PRAGMA page_size = 4096")
    db.execute("PRAGMA journal_mode = DELETE")
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    db.execute("CREATE TABLE place (id INTEGER PRIMARY KEY, kind INTEGER, name TEXT, folded TEXT, detail TEXT,"
               " area TEXT, keys TEXT, lat INTEGER, lon INTEGER, rank INTEGER)")
    db.execute("CREATE VIRTUAL TABLE words USING fts4(content=\"\", head)")
    db.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("version", str(VERSION)), ("region", region),
        ("source_date", source_date.isoformat() if source_date else ""),
        ("built", datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))])
    for i, (kind, name, detail, area, lat, lon, rank) in enumerate(rows, 1):
        db.execute("INSERT INTO place VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (i, kind, name, fold(name), detail, area, " " + keywords(name, detail, area),
                    int(round(lat * 1e6)), int(round(lon * 1e6)), rank))
        db.execute("INSERT INTO words (docid, head) VALUES (?, ?)", (i, keywords(name, detail)))
    db.execute("INSERT INTO words (words) VALUES ('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()
    os.replace(tmp, out)
    counts = {}
    for r in rows:
        counts[r[0]] = counts.get(r[0], 0) + 1
    return {"rows": len(rows), "bytes": os.path.getsize(out), "kinds": counts}


def where(text):
    """(SQL condition, its arguments) for what was typed, or None when it is too short to search."""
    words = fold(text).split()
    if not words or len(" ".join(words)) < 3:
        return None
    cond = "words MATCH ?" + " AND p.keys LIKE ?" * (len(words) - 1)
    return cond, [words[0] + "*"] + ["%% %s%%" % w for w in words[1:]]


def query(db_path, text, lat=None, lon=None, limit=8):
    """Searches a built file the way the app does (Search.java), for checking a build here."""
    w = where(text)
    if not w:
        return []
    cond, args = w
    q = fold(text)
    words = q.split()
    cols = "p.id, p.kind, p.name, p.folded, p.detail, p.area, p.lat, p.lon, p.rank"
    base = "SELECT %s FROM words w JOIN place p ON p.id = w.docid WHERE %s" % (cols, cond)
    db = sqlite3.connect(db_path)
    try:
        got = {r[0]: r for r in db.execute(base + " ORDER BY p.rank DESC LIMIT %d" % BEST, args)}
        if lat is not None:
            la, lo = int(lat * 1e6), int(lon * 1e6)
            k = round(math.cos(math.radians(lat)) ** 2 * 1000)
            near = db.execute(base + " ORDER BY (p.lat - ?) * (p.lat - ?) * 1000 + (p.lon - ?) * (p.lon - ?) * ? LIMIT %d"
                              % NEAR, args + [la, la, lo, lo, k])
            got.update({r[0]: r for r in near})
    finally:
        db.close()

    def score(r):
        s = r[8]
        if r[3] == q:
            s += 40
        elif r[3].startswith(q):
            s += 25
        elif r[3].startswith(words[0]):
            s += 15
        if words[0].isdigit() and r[3].split(" ")[0] != words[0]:
            s -= 30                     # "12 york": 12 York Street, not 124
        if lat is not None:
            d = math.hypot((r[6] / 1e6 - lat) * 111.2, (r[7] / 1e6 - lon) * 111.2 * math.cos(math.radians(lat)))
            s -= 12 * math.log10(1 + d)
        return -s

    out = [{"kind": r[1], "name": r[2], "detail": r[4], "area": r[5], "lat": r[6] / 1e6, "lon": r[7] / 1e6}
           for r in sorted(got.values(), key=score)[:limit]]
    if words[0].isdigit() and len(words) > 1 and not any(fold(r["name"]).startswith(words[0] + " ") for r in out):
        guess = estimate(db_path, words[0], " ".join(words[1:]), lat, lon)
        if guess:
            out = [guess] + out[:limit - 1]
    return out


def _number(folded):
    m = re.match(r"(\d+)", folded)
    return int(m.group(1)) if m else None


def estimate(db_path, number, rest, lat=None, lon=None):
    """A house number that is not mapped ("32 york street george"): the street found for the rest, and
    the spot between the nearest mapped numbers on the same side of it, else at the nearest mapped
    number (Search.estimate does the same). Without mapped numbers on that street, the street itself."""
    streets = [r for r in query(db_path, rest, lat, lon, 8) if r["kind"] == STREET]
    if not streets:
        return None
    st = streets[0]
    street = fold(st["name"])
    town = st["area"].rpartition(", ")[2]
    n = int(number)
    db = sqlite3.connect(db_path)
    try:
        rows = db.execute("SELECT p.folded, p.area, p.lat, p.lon FROM words w JOIN place p ON p.id = w.docid"
                          " WHERE words MATCH ? AND p.kind = ? AND p.folded LIKE ? AND p.area LIKE ?",
                          (street.split(" ")[0] + "*", ADDRESS, "% " + street, "%" + town)).fetchall()
    finally:
        db.close()
    mapped = [(_number(f), a, la / 1e6, lo / 1e6) for f, a, la, lo in rows if f == "%d %s" % (_number(f) or -1, street)]

    def bracket(xs):
        return max((x for x in xs if x[0] < n), default=None), min((x for x in xs if x[0] > n), default=None)

    # between numbers on the same side of the street; failing that, the nearest numbers on either side
    below, above = bracket([x for x in mapped if x[0] % 2 == n % 2])
    if not (below and above):
        below, above = bracket(mapped)
        if below and above:
            below, above = (below, None) if n - below[0] <= above[0] - n else (None, above)
    name = "%s %s" % (number, st["name"])
    if below and above:
        t = (n - below[0]) / (above[0] - below[0])
        return {"kind": ADDRESS, "name": name, "detail": "Estimated, between %d and %d" % (below[0], above[0]),
                "area": below[1], "lat": below[2] + t * (above[2] - below[2]), "lon": below[3] + t * (above[3] - below[3])}
    one = below or above
    if one:
        return {"kind": ADDRESS, "name": name, "detail": "Estimated, near %d" % one[0], "area": one[1],
                "lat": one[2], "lon": one[3]}
    return dict(st, detail="Number %s is not mapped" % number)


# ---- the card ----

def db_name(region=None):
    region = region or maps.chosen()
    return os.path.basename(region)[:-4] + ".db"


def local_db(region=None):
    return os.path.join(cache_dir(), "search", db_name(region))


def _meta(path):
    try:
        db = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        try:
            return dict(db.execute("SELECT key, value FROM meta").fetchall())
        finally:
            db.close()
    except sqlite3.Error:
        return {}


def prepare(region=None, progress=None, log=print):
    """The search file for the region, building it when missing, older than the source or of an
    older version. `progress(done, total)` while downloading the extract."""
    region = region or maps.chosen()
    if not region:
        raise SystemExit("no region chosen yet: run  maps choose")
    pbf, date = source(source_url(region), progress)
    out = local_db(region)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    meta = _meta(out) if os.path.exists(out) else {}
    if meta.get("version") == str(VERSION) and meta.get("source_date") == date.isoformat():
        return out, False
    log("building the search index from %s ..." % os.path.basename(pbf))
    r = build(pbf, out, region, date, log)
    log("search index: %d rows, %.0f MB" % (r["rows"], r["bytes"] / 1e6))
    return out, True


def installed(target):
    return [e for e in target.listdir(SEARCH_DIR) if e.name.endswith(".db")]


def sync(target, progress=None, copying=None, region=None, log=print):
    """Puts the region's search file on the card and removes others. Returns a summary dict."""
    path, built = prepare(region, progress, log)
    if copying:
        copying()
    name = os.path.basename(path)
    size = os.path.getsize(path)
    out = {"file": name, "bytes": size, "built": built, "copied": False, "removed": 0}
    on_card = {e.name: e.size for e in installed(target)}
    if on_card.get(name) != size:
        target.push(path, SEARCH_DIR + "/" + name)
        got = [e for e in installed(target) if e.name == name]
        if not got or got[0].size != size:
            raise RuntimeError("copy failed: %s on the card has the wrong size" % name)
        out["copied"] = True
    for other in on_card:
        if other != name:
            target.remove(SEARCH_DIR + "/" + other)
            out["removed"] += 1
    return out
