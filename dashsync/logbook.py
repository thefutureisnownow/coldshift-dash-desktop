"""The log book on the computer: trips, fill-ups, odometer readings and services, copied from the phone and
edited here; fuel use, monthly figures, a CSV of everything and the SARS travel logbook for a tax year.

The app keeps one file per entry in its folder on the card (LogStore.java):
    <card>/Android/data/racing.coldshift.dash/files/log/entries/<id>.json
        {"version": 1, "id", "type", "time", "updated", "deleted"?, ...}
    trip      "end", "dist_m" (GPS), "max" (m/s), "from"/"to" {"name", "lat", "lon"}, "business", "purpose",
              "odo_start"/"odo_end"
    fuel      "odometer", "litres", "price", "total", "grade", "full", "missed", "station", "lat", "lon"
    odometer  "odometer"
    service   "odometer", "what", "cost"
    reminder  "what", "every_km", "every_months" (0: not by that), "from_odometer" (with "time": when it was last
              done, until a service of the same name is logged)
    .../log/routes/<trip id>.csv   the trip's route, "time_ms,lat,lon,speed" lines (current.csv while it runs)
Times are milliseconds since 1970; an entry is deleted by marking it, and the copy with the later "updated"
wins. `sync_to_pc` copies the phone's into <vehicle>/log/entries/ (and routes into log/routes/); entries made or changed here go back in
<card>/coldshift.dash/log/desktop.json ({"entries": [...]}), which the app takes in.

The odometer between readings is the last reading plus the GPS distance driven since, times a factor
learned from readings far enough apart; fuel use runs from one full tank to the next (as LogStore.java).
"""
import csv
import datetime
import json
import os
import random
import tempfile
import time
from html import escape
from xml.sax.saxutils import escape as xml

from . import layout

PHONE = layout.APP_DATA + "/log/entries"
PHONE_ROUTES = layout.APP_DATA + "/log/routes"
SHARED = layout.APP_DIR + "/log/desktop.json"
TYPES = ("trip", "fuel", "odometer", "service", "reminder")
GRADES = ("95", "93", "Diesel 50", "Diesel 500")


def _dir(vehicle, *parts):
    return os.path.join(vehicle, "log", *parts)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(path + ".part", path)


def now_ms():
    return int(time.time() * 1000)


def make(kind, when_ms):
    if kind not in TYPES:
        raise ValueError("no entry type %r" % kind)
    return {"version": 1, "id": "%s-%d-%x" % (kind, now_ms(), random.randrange(0x10000)), "type": kind,
            "time": int(when_ms)}


# ---- entries here ----

def entries(vehicle, deleted=False):
    """The vehicle's entries, newest first."""
    out = []
    d = _dir(vehicle, "entries")
    for name in os.listdir(d) if os.path.isdir(d) else []:
        if not name.endswith(".json"):
            continue
        try:
            e = _read(os.path.join(d, name))
        except (OSError, ValueError):
            continue
        if deleted or not e.get("deleted"):
            out.append(e)
    return sorted(out, key=lambda e: -e.get("time", 0))


def check(e):
    """Raises ValueError when an entry lacks what its type needs."""
    t = e.get("type")
    if t == "fuel":
        if not (e.get("litres", 0) > 0 and e.get("total", 0) > 0):
            raise ValueError("a fill-up needs the litres and the total (or the price per litre)")
    elif t == "odometer":
        if not e.get("odometer", 0) > 0:
            raise ValueError("give the odometer reading")
    elif t == "service":
        if not str(e.get("what", "")).strip():
            raise ValueError("say what was done")
    elif t == "trip":
        if not (e.get("end", 0) >= e.get("time", 0) and e.get("dist_m", 0) > 0):
            raise ValueError("a trip needs an end after its start and a distance")
    elif t == "reminder":
        if not str(e.get("what", "")).strip():
            raise ValueError("say what the reminder is for")
        if not (e.get("every_km", 0) > 0 or e.get("every_months", 0) > 0):
            raise ValueError("give a distance or a number of months (or both)")
    else:
        raise ValueError("no entry type %r" % t)


def put(vehicle, e):
    """Saves an entry made or changed here (it goes to the phone with the next Sync to card)."""
    check(e)
    e = dict(e)
    e["updated"] = now_ms()
    _write(_dir(vehicle, "entries", e["id"] + ".json"), e)
    ids = _local(vehicle) | {e["id"]}
    _write(_dir(vehicle, "local.json"), sorted(ids))
    return e


def delete(vehicle, eid):
    path = _dir(vehicle, "entries", eid + ".json")
    e = _read(path)
    e["deleted"] = True
    e["updated"] = now_ms()
    _write(path, e)
    _write(_dir(vehicle, "local.json"), sorted(_local(vehicle) | {eid}))


def _local(vehicle):
    try:
        return set(_read(_dir(vehicle, "local.json")))
    except (OSError, ValueError):
        return set()


def vehicle_text(vehicle):
    """The make, model and registration for the logbook's heading, as typed when it was last made."""
    try:
        return _read(_dir(vehicle, "settings.json")).get("vehicle", "")
    except (OSError, ValueError):
        return ""


def set_vehicle_text(vehicle, text):
    _write(_dir(vehicle, "settings.json"), {"vehicle": text.strip()})


# ---- the phone ----

def sync_to_pc(target, vehicle):
    """Copies the phone's entries that are new or newer than the copy here, and the trips' routes. Returns
    {"new", "updated", "routes"}."""
    out = {"new": 0, "updated": 0, "routes": 0}
    tmp = tempfile.mkdtemp(prefix="dashsync-log-")
    phone, phone_routes = layout.on_phone(target, PHONE), layout.on_phone(target, PHONE_ROUTES)
    try:
        for e in target.listdir(phone):
            if not e.name.endswith(".json"):
                continue
            local = _dir(vehicle, "entries", e.name)
            if os.path.exists(local) and os.path.getsize(local) == e.size:
                continue
            got = os.path.join(tmp, e.name)
            target.pull(phone + "/" + e.name, got)
            try:
                theirs = _read(got)
            except (OSError, ValueError):
                continue
            if not os.path.exists(local):
                _write(local, theirs)
                out["new"] += 1
            elif theirs.get("updated", 0) > _read(local).get("updated", 0):
                _write(local, theirs)
                out["updated"] += 1
    finally:
        for name in os.listdir(tmp):
            os.remove(os.path.join(tmp, name))
        os.rmdir(tmp)
    for e in target.listdir(phone_routes):
        local = _dir(vehicle, "routes", e.name)
        if e.name.endswith(".csv") and e.name != "current.csv" and not os.path.exists(local):
            os.makedirs(os.path.dirname(local), exist_ok=True)
            target.pull(phone_routes + "/" + e.name, local + ".part")
            os.replace(local + ".part", local)
            out["routes"] += 1
    return out


def route(vehicle, trip_id):
    """A trip's route as [(time_ms, lat, lon, speed m/s)], empty when there is none (trips from before routes
    were kept, or added by hand)."""
    out = []
    try:
        with open(_dir(vehicle, "routes", trip_id + ".csv"), encoding="utf-8") as f:
            for line in f:
                p = line.strip().split(",")
                if len(p) == 4:
                    out.append((int(p[0]), float(p[1]), float(p[2]), float(p[3])))
    except (OSError, ValueError):
        pass
    return out


def _utc(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def trips_gpx(vehicle, trips):
    """A GPX file with a track per trip that has a route (named by its date and ends, described by its
    purpose), with the time and speed at each point (speed in Garmin's TrackPointExtension, m/s). Returns (text, how many trips it has)."""
    tracks = []
    for t in sorted(trips, key=lambda e: e["time"]):
        pts = route(vehicle, t["id"]) if t.get("type") == "trip" else []
        if len(pts) < 2:
            continue
        name = "%s %s → %s" % (_when(t["time"]), _place(t, "from") or "…", _place(t, "to") or "…")
        desc = ("Business: " + t.get("purpose", "")) if t.get("business") else "Private"
        seg = "".join('<trkpt lat="%.6f" lon="%.6f"><time>%s</time><extensions><gpxtpx:TrackPointExtension>'
                      '<gpxtpx:speed>%.1f</gpxtpx:speed></gpxtpx:TrackPointExtension></extensions></trkpt>\n'
                      % (la, lo, _utc(ms), v) for ms, la, lo, v in pts)
        tracks.append("<trk><name>%s</name><desc>%s</desc><type>%s</type><trkseg>\n%s</trkseg></trk>\n"
                      % (xml(name), xml(desc), "business" if t.get("business") else "private", seg))
    text = ('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="coldshift.dash" '
            'xmlns="http://www.topografix.com/GPX/1/1" '
            'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v2">\n<metadata><name>Trips</name></metadata>\n%s</gpx>\n'
            % "".join(tracks))
    return text, len(tracks)


def export_gpx(vehicle, trips, path):
    """Writes trips_gpx to a file. Returns how many trips it holds (0: nothing written)."""
    text, n = trips_gpx(vehicle, trips)
    if n:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return n


def sync_to_card(target, vehicle):
    """Puts the entries made or changed here where the app takes them in. Returns {"entries", "app"}."""
    ids = _local(vehicle)
    sent = []
    for eid in sorted(ids):
        try:
            sent.append(_read(_dir(vehicle, "entries", eid + ".json")))
        except (OSError, ValueError):
            continue
    if not sent:
        return {"entries": 0, "app": None}
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"entries": sent}, f)
        target.push(path, SHARED)
    finally:
        os.remove(path)
    return {"entries": len(sent), "app": target.notify_synced(["log"])}


def restore(target, vehicle):
    """Puts every entry here (deleted ones too) where the app takes them in, e.g. on a new phone. Returns how
    many."""
    es = entries(vehicle, deleted=True)
    if not es:
        return 0
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"entries": es}, f)
        target.push(path, SHARED)
    finally:
        os.remove(path)
    return len(es)


# ---- the odometer ----

def readings(es):
    """(time, km) of every odometer reading (fill-ups, readings, services), oldest first."""
    return sorted((e["time"], e["odometer"]) for e in es if e.get("type") != "trip" and e.get("odometer", 0) > 0)


def gps_metres(es, start, end):
    """GPS metres driven between two moments: whole trips, and the share by time of one spanning either."""
    m = 0.0
    for e in es:
        if e.get("type") != "trip":
            continue
        s, t, d = e["time"], max(e["time"], e.get("end", e["time"])), e.get("dist_m", 0)
        if t == s:
            m += d if start <= s <= end else 0
        else:
            inside = min(t, end) - max(s, start)
            if inside > 0:
                m += d * inside / (t - s)
    return m


def factor(es):
    """Odometer km per GPS km, from pairs of readings with at least 30 km of trips between them."""
    r = readings(es)
    odo = gps = 0.0
    for (t1, k1), (t2, k2) in zip(r, r[1:]):
        g, d = gps_metres(es, t1, t2) / 1000, k2 - k1
        if g < 30 or d <= 0 or not 0.9 <= d / g <= 1.15:
            continue
        odo += d
        gps += g
    return odo / gps if gps else 1.0


def odometer_at(es, when, k=None):
    """The odometer at a moment: from the reading before it, else back from the one after; None without any."""
    r = readings(es)
    if not r:
        return None
    k = factor(es) if k is None else k
    before = [x for x in r if x[0] <= when]
    if before:
        t, km = before[-1]
        return km + k * gps_metres(es, t, when) / 1000
    t, km = r[0]
    return km - k * gps_metres(es, when, t) / 1000


def trip_km(e, k):
    return e.get("dist_m", 0) * k / 1000


# ---- fuel ----

def consumption(es):
    """[(time, L/100 km, km)] for each full tank after another full tank, oldest first."""
    out = []
    full, litres = None, 0.0
    for f in sorted((e for e in es if e.get("type") == "fuel"), key=lambda e: e["time"]):
        if f.get("missed"):
            full, litres = (f if f.get("full", True) else None), 0.0
            continue
        litres += f.get("litres", 0)
        if not f.get("full", True):
            continue
        if full is not None and full.get("odometer", 0) > 0:
            km = f.get("odometer", 0) - full["odometer"]
            if km > 0:
                out.append((f["time"], litres / km * 100, km))
        full, litres = f, 0.0
    return out


def average_l100(es):
    c = consumption(es)
    km = sum(x[2] for x in c)
    return sum(x[1] * x[2] / 100 for x in c) / km * 100 if km else None


def work_out(litres=None, price=None, total=None):
    """Fills in the missing one of litres, price per litre and total. Returns (litres, price, total)."""
    if litres and price and not total:
        total = round(litres * price, 2)
    elif litres and total and not price:
        price = round(total / litres, 2)
    elif price and total and not litres:
        litres = round(total / price, 2)
    return litres, price, total


# ---- service reminders ----

SOON_KM, SOON_DAYS = 1000, 30
PRESETS = [("Oil change", 10000, 12), ("Service", 15000, 12), ("Tyre rotation", 10000, 0), ("Brake fluid", 0, 24),
           ("Timing belt", 100000, 60), ("Licence renewal", 0, 12), ("Battery check", 0, 12)]


def _add_months(dt, n):
    y, m = divmod(dt.month - 1 + n, 12)
    y += dt.year
    days = [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m]
    return dt.replace(year=y, month=m + 1, day=min(dt.day, days))


def reminders(es, now=None):
    """Each reminder with when it was last done (the last service of the same name, else its starting point)
    and what is left, the most urgent first: {"entry", "what", "last_time", "last_odo", "km_left" (None: not by
    distance, or no odometer yet), "days_left" (None: not by time), "due_odo", "due_time", "overdue", "soon",
    "urgency" (the share of the interval left, the smaller of the two)}, as LogStore.reminders."""
    now = now or now_ms()
    k = factor(es)
    odo_now = odometer_at(es, now, k)
    out = []
    for r in es:
        if r.get("type") != "reminder":
            continue
        what = r.get("what", "").strip()
        last_t, last_o = r["time"], r.get("from_odometer") or None
        done = [s for s in es if s.get("type") == "service" and s.get("what", "").strip().lower() == what.lower()
                and s["time"] >= last_t]
        if done:
            s = max(done, key=lambda s: s["time"])
            last_t, last_o = s["time"], s.get("odometer") or None
        if not last_o:
            last_o = odometer_at(es, last_t, k)
        every_km, months = r.get("every_km", 0) or 0, r.get("every_months", 0) or 0
        d = {"entry": r, "what": what, "last_time": last_t, "last_odo": last_o, "km_left": None, "days_left": None,
             "due_odo": None, "due_time": None}
        urg = []
        if every_km and last_o is not None and odo_now is not None:
            d["due_odo"] = last_o + every_km
            d["km_left"] = d["due_odo"] - odo_now
            urg.append(d["km_left"] / every_km)
        if months:
            start = datetime.datetime.fromtimestamp(last_t / 1000)
            due = _add_months(start, months)
            d["due_time"] = int(due.timestamp() * 1000)
            d["days_left"] = int((d["due_time"] - now) / 86400000)          # whole days, either way
            urg.append((d["due_time"] - now) / (d["due_time"] - last_t))
        if not urg:
            continue
        d["urgency"] = min(urg)
        d["overdue"] = (d["km_left"] is not None and d["km_left"] <= 0) or (d["due_time"] is not None and d["due_time"] <= now)
        d["soon"] = d["overdue"] or (d["km_left"] is not None and d["km_left"] <= SOON_KM) or \
            (d["days_left"] is not None and d["days_left"] <= SOON_DAYS)
        out.append(d)
    return sorted(out, key=lambda d: d["urgency"])


def due_text(d):
    """'in 850 km', 'in 12 days', '120 km overdue'...: by whichever comes first."""
    by_km = d["km_left"] is not None and (d["days_left"] is None or
                                          d["km_left"] / max(1, d["entry"].get("every_km", 1)) <= d["urgency"] + 1e-9)
    if by_km:
        n = "{:,.0f} km".format(abs(d["km_left"])).replace(",", " ")
    else:
        days = abs(d["days_left"])
        if days == 0:
            return "today"
        n = "%d day%s" % (days, "" if days == 1 else "s") if days < 60 else "%d months" % (days // 30)
    over = d["km_left"] <= 0 if by_km else d["due_time"] <= now_ms() if d["days_left"] == 0 else d["days_left"] < 0
    return n + " overdue" if over else "in " + n


# ---- figures ----

def months(es):
    """Per month, newest first: {"month": "2026-11", "fills", "litres", "fuel_cost", "km", "business_km",
    "service_cost", "l100" (full tanks ending that month, or None), "cost_per_km" (that fuel use at that month's
    price per litre, or None)}."""
    k = factor(es)
    rows = {}

    def row(t):
        key = datetime.datetime.fromtimestamp(t / 1000).strftime("%Y-%m")
        return rows.setdefault(key, {"month": key, "fills": 0, "litres": 0.0, "fuel_cost": 0.0, "km": 0.0,
                                     "business_km": 0.0, "service_cost": 0.0, "_l": 0.0, "_km": 0.0})
    for e in es:
        if e["type"] not in ("fuel", "trip", "service"):
            continue
        r = row(e["time"])
        if e["type"] == "fuel":
            r["fills"] += 1
            r["litres"] += e.get("litres", 0)
            r["fuel_cost"] += e.get("total", 0)
        elif e["type"] == "trip":
            r["km"] += trip_km(e, k)
            if e.get("business"):
                r["business_km"] += trip_km(e, k)
        elif e["type"] == "service":
            r["service_cost"] += e.get("cost", 0) or 0
    for t, l100, km in consumption(es):
        r = row(t)
        r["_l"] += l100 * km / 100
        r["_km"] += km
    out = []
    for key in sorted(rows, reverse=True):
        r = rows[key]
        r["l100"] = r["_l"] / r["_km"] * 100 if r["_km"] else None
        r["cost_per_km"] = r["l100"] / 100 * r["fuel_cost"] / r["litres"] if r["l100"] and r["litres"] else None
        del r["_l"], r["_km"]
        out.append(r)
    return out


# ---- exports ----

def _when(ms, fmt="%Y-%m-%d %H:%M"):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime(fmt)


def _place(e, key):
    return (e.get(key) or {}).get("name", "")


def export_csv(es, path):
    """Every entry, oldest first, one row each."""
    k = factor(es)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "type", "from", "to", "km", "business", "purpose", "odometer", "litres", "price_per_litre",
                    "total", "grade", "full_tank", "station", "what", "cost"])
        for e in sorted((e for e in es if e["type"] != "reminder"), key=lambda e: e["time"]):
            t = e["type"]
            w.writerow([_when(e["time"]), t, _place(e, "from"), _place(e, "to"),
                        "%.1f" % trip_km(e, k) if t == "trip" else "",
                        ("yes" if e.get("business") else "no") if t == "trip" else "", e.get("purpose", ""),
                        e.get("odometer", ""), e.get("litres", ""), e.get("price", ""), e.get("total", ""),
                        e.get("grade", ""), ("yes" if e.get("full", True) else "no") if t == "fuel" else "",
                        e.get("station", ""), e.get("what", ""), e.get("cost", "")])
    return path


def tax_year(year):
    """The SARS year of assessment ending in February of `year`: (1 March year-1, end of February year)."""
    start = datetime.datetime(year - 1, 3, 1)
    return start, datetime.datetime(year, 3, 1) - datetime.timedelta(milliseconds=1)


def current_tax_year(today=None):
    today = today or datetime.date.today()
    return today.year + 1 if today.month >= 3 else today.year


def sars(es, year):
    """The travel logbook for the year of assessment ending February `year`: the opening and closing odometer,
    every business trip with its odometer, distance and purpose, and the totals."""
    start, end = tax_year(year)
    s, e_ = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    k = factor(es)
    trips = sorted((e for e in es if e["type"] == "trip" and s <= e["time"] <= e_), key=lambda e: e["time"])
    rows, business = [], 0.0
    for t in trips:
        if not t.get("business"):
            continue
        km = trip_km(t, k)
        odo = odometer_at(es, t["time"], k)
        business += km
        rows.append({"date": _when(t["time"], "%Y-%m-%d"), "from": _place(t, "from"), "to": _place(t, "to"),
                     "purpose": t.get("purpose", ""), "km": km,
                     "odo_start": odo, "odo_end": odo + km if odo is not None else None})
    opening, closing = odometer_at(es, s, k), odometer_at(es, min(e_, now_ms()), k)
    total = closing - opening if opening is not None and closing is not None else sum(trip_km(t, k) for t in trips)
    missing = [r for r in rows if not r["purpose"].strip()]
    return {"year": year, "start": start.date(), "end": end.date(), "opening": opening, "closing": closing,
            "total_km": total, "business_km": business, "private_km": max(0.0, total - business), "trips": rows,
            "logged_km": sum(trip_km(t, k) for t in trips), "factor": k, "no_purpose": len(missing),
            "readings": len([r for r in readings(es) if s <= r[0] <= e_])}


def _km(v):
    return "" if v is None else "{:,.0f}".format(v).replace(",", " ")


def sars_csv(report, path, vehicle_text=""):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Travel logbook", "Year of assessment %d-03-01 to %s" % (report["year"] - 1, report["end"])])
        if vehicle_text:
            w.writerow(["Vehicle", vehicle_text])
        w.writerow(["Opening odometer", _km(report["opening"])])
        w.writerow(["Closing odometer", _km(report["closing"])])
        w.writerow(["Total km", "%.0f" % report["total_km"]])
        w.writerow(["Business km", "%.0f" % report["business_km"]])
        w.writerow(["Private km", "%.0f" % report["private_km"]])
        w.writerow([])
        w.writerow(["Date", "Opening km", "Closing km", "Business km", "From", "To", "Where to and why"])
        for r in report["trips"]:
            w.writerow([r["date"], _km(r["odo_start"]), _km(r["odo_end"]), "%.1f" % r["km"], r["from"], r["to"],
                        r["purpose"]])
    return path


def sars_html(report, vehicle_text=""):
    """The logbook as a page to print or turn into a PDF (table attributes rather than CSS for spacing, which
    Qt's renderer ignores)."""
    rows = "".join(
        "<tr><td style='white-space: nowrap'>%s</td><td align=right>%s</td><td align=right>%s</td>"
        "<td align=right>%.1f</td><td>%s → %s</td><td>%s</td></tr>"
        % (escape(r["date"]), _km(r["odo_start"]), _km(r["odo_end"]), r["km"], escape(r["from"]), escape(r["to"]),
           escape(r["purpose"])) for r in report["trips"])
    facts = [("Year of assessment", "%s to %s" % (report["start"], report["end"]))]
    if vehicle_text:
        facts.append(("Vehicle", vehicle_text))
    facts += [("Opening odometer", _km(report["opening"]) + " km"), ("Closing odometer", _km(report["closing"]) + " km"),
              ("Total distance", "%.0f km" % report["total_km"]), ("Business distance", "%.0f km" % report["business_km"]),
              ("Private distance", "%.0f km" % report["private_km"])]
    head = "".join("<tr><td style='color: #555'>%s</td><td>%s</td></tr>" % (escape(a), escape(b)) for a, b in facts)
    return """<html><head><meta charset="utf-8"></head><body style="font-family: Helvetica, Arial, sans-serif; font-size: 9pt">
<h1 style="font-size: 16pt">Travel logbook</h1>
<table cellpadding=3 cellspacing=0>%s</table>
<p></p>
<table width="100%%" cellpadding=5 cellspacing=0 border=1 style="border-color: #bbb; border-style: solid">
<tr bgcolor="#eeeeee"><th align=left>Date</th><th align=right>Opening km</th><th align=right>Closing km</th>
<th align=right>Business km</th><th align=left>Trip</th><th align=left>Where to and why</th></tr>%s</table>
<p style="color: #555; font-size: 7.5pt">Trips logged by GPS (distances scaled to the odometer by %.3f, from the
readings). Odometer readings between those typed in are estimates. Made by coldshift.dash.</p>
</body></html>""" % (head, rows or "<tr><td colspan=6>No business trips this year.</td></tr>", report["factor"])
