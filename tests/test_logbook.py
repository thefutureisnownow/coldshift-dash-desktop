import datetime
import json
import os
import shutil
import tempfile
import unittest

from dashsync import backup, logbook
from dashsync.transport import FolderTarget

H = 3600 * 1000


def ms(*args):
    return int(datetime.datetime(*args).timestamp() * 1000)


def trip(start, km, business=False, purpose="", minutes=30):
    e = logbook.make("trip", start)
    e.update({"end": start + minutes * 60000, "dist_m": km * 1000, "business": business, "purpose": purpose,
              "from": {"name": "Home"}, "to": {"name": "Acme & Sons"}})
    return e


def reading(when, km, kind="odometer", **more):
    e = logbook.make(kind, when)
    e["odometer"] = km
    e.update(more)
    return e


def fuel(when, odo, litres, full=True, missed=False, price=23.0):
    return reading(when, odo, "fuel", litres=litres, price=price, total=round(litres * price, 2), full=full,
                   missed=missed, grade="95")


class LogbookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.v = os.path.join(self.tmp, "vehicle")
        self.card = os.path.join(self.tmp, "card")
        self.phone = os.path.join(self.card, *logbook.PHONE.split("/"))
        os.makedirs(self.phone)
        self.target = FolderTarget(self.card)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def on_phone(self, e, updated):
        e = dict(e, updated=updated)
        with open(os.path.join(self.phone, e["id"] + ".json"), "w") as f:
            json.dump(e, f)
        return e

    # ---- syncing ----

    def test_sync_to_pc_takes_new_and_newer_and_keeps_newer_here(self):
        a = self.on_phone(trip(ms(2026, 5, 1, 8), 20), 100)
        b = self.on_phone(reading(ms(2026, 5, 1, 9), 50000), 100)
        self.assertEqual(logbook.sync_to_pc(self.target, self.v), {"new": 2, "updated": 0, "routes": 0})
        self.assertEqual(logbook.sync_to_pc(self.target, self.v), {"new": 0, "updated": 0, "routes": 0})
        # the phone marks the trip business; here the reading is corrected (later)
        self.on_phone(dict(a, business=True, purpose="Client visit"), 200)
        logbook.put(self.v, dict(b, odometer=50010))
        self.on_phone(dict(b, odometer=49999), 150)
        self.assertEqual(logbook.sync_to_pc(self.target, self.v), {"new": 0, "updated": 1, "routes": 0})
        es = {e["id"]: e for e in logbook.entries(self.v)}
        self.assertTrue(es[a["id"]]["business"])
        self.assertEqual(es[b["id"]]["odometer"], 50010)

    def test_sync_to_card_sends_only_what_changed_here_deleted_ones_too(self):
        a = self.on_phone(trip(ms(2026, 5, 1, 8), 20), 100)
        self.on_phone(trip(ms(2026, 5, 2, 8), 30), 100)
        logbook.sync_to_pc(self.target, self.v)
        self.assertEqual(logbook.sync_to_card(self.target, self.v), {"entries": 0, "app": None})
        logbook.put(self.v, dict(a, business=True, purpose="Site visit"))
        added = logbook.put(self.v, fuel(ms(2026, 5, 3, 8), 50500, 40))
        logbook.delete(self.v, added["id"])
        self.assertEqual(logbook.sync_to_card(self.target, self.v)["entries"], 2)
        with open(os.path.join(self.card, *logbook.SHARED.split("/"))) as f:
            sent = {e["id"]: e for e in json.load(f)["entries"]}
        self.assertEqual(sent[a["id"]]["purpose"], "Site visit")
        self.assertTrue(sent[added["id"]]["deleted"])
        self.assertEqual(len(logbook.entries(self.v)), 2)
        self.assertEqual(len(logbook.entries(self.v, deleted=True)), 3)

    def test_restore_sends_everything_and_backup_copies_the_log_book(self):
        self.on_phone(trip(ms(2026, 5, 1, 8), 20), 100)
        self.assertIn("log book", backup.backup(self.target, self.v)["changed"])
        self.assertEqual(logbook.restore(self.target, self.v), 1)

    def test_routes_are_copied_and_exported_as_gpx(self):
        t0 = ms(2026, 5, 1, 8)
        a = self.on_phone(trip(t0, 1, business=True, purpose="Client & partner"), 100)
        b = self.on_phone(trip(t0 + H, 1), 100)                    # no route: left out of the GPX
        routes = os.path.join(self.card, *logbook.PHONE_ROUTES.split("/"))
        os.makedirs(routes)
        with open(os.path.join(routes, a["id"] + ".csv"), "w") as f:
            f.write("%d,-34.000000,22.500000,0.0\n%d,-34.000900,22.500000,15.0\n" % (t0, t0 + 6000))
        with open(os.path.join(routes, "current.csv"), "w") as f:
            f.write("%d,-34.1,22.6,3.0\n" % t0)
        self.assertEqual(logbook.sync_to_pc(self.target, self.v)["routes"], 1)
        self.assertEqual(logbook.sync_to_pc(self.target, self.v)["routes"], 0)
        self.assertEqual(len(logbook.route(self.v, a["id"])), 2)
        self.assertEqual(logbook.route(self.v, b["id"]), [])
        path = os.path.join(self.tmp, "trips.gpx")
        self.assertEqual(logbook.export_gpx(self.v, logbook.entries(self.v), path), 1)
        with open(path) as f:
            text = f.read()
        self.assertIn('<trkpt lat="-34.000900" lon="22.500000">', text)
        self.assertIn("<gpxtpx:speed>15.0</gpxtpx:speed>", text)
        import xml.dom.minidom
        xml.dom.minidom.parseString(text.encode())
        self.assertIn("<desc>Business: Client &amp; partner</desc>", text)
        self.assertIn("<time>%s</time>" % datetime.datetime.fromtimestamp(t0 / 1000, datetime.timezone.utc)
                      .strftime("%Y-%m-%dT%H:%M:%SZ"), text)
        self.assertEqual(logbook.export_gpx(self.v, [b], os.path.join(self.tmp, "none.gpx")), 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "none.gpx")))

    def test_check(self):
        with self.assertRaises(ValueError):
            logbook.check(logbook.make("fuel", 1))
        with self.assertRaises(ValueError):
            logbook.check(logbook.make("service", 1))
        with self.assertRaises(ValueError):
            logbook.make("parking", 1)
        logbook.check(fuel(1, 0, 30))

    # ---- the odometer and fuel ----

    def test_factor_and_odometer_between_readings(self):
        t0 = ms(2026, 5, 1, 8)
        es = [reading(t0, 10000), trip(t0 + H, 60), trip(t0 + 3 * H, 40), reading(t0 + 5 * H, 10102)]
        self.assertAlmostEqual(logbook.factor(es), 1.02)
        self.assertAlmostEqual(logbook.odometer_at(es, t0 + 2 * H), 10000 + 61.2)
        # half way through the second trip
        self.assertAlmostEqual(logbook.odometer_at(es, t0 + 3 * H + 15 * 60000), 10000 + 1.02 * 80)
        # before the first reading: worked back from it
        es2 = [trip(t0 - 2 * H, 50), reading(t0, 10000)]
        self.assertAlmostEqual(logbook.odometer_at(es2, t0 - 3 * H), 9950)
        self.assertIsNone(logbook.odometer_at([trip(t0, 10)], t0))

    def test_a_reading_far_off_does_not_teach_the_factor(self):
        t0 = ms(2026, 5, 1, 8)
        es = [reading(t0, 10000), trip(t0 + H, 60), reading(t0 + 5 * H, 10500)]      # driving not logged
        self.assertEqual(logbook.factor(es), 1.0)

    def test_consumption_full_to_full(self):
        t = ms(2026, 5, 1, 8)
        es = [fuel(t, 1000, 50), fuel(t + H, 1200, 20, full=False), fuel(t + 2 * H, 1600, 30),
              fuel(t + 3 * H, 2000, 32, missed=True), fuel(t + 4 * H, 2500, 40)]
        c = logbook.consumption(es)
        self.assertEqual(len(c), 2)
        self.assertAlmostEqual(c[0][1], 50 / 600 * 100)
        self.assertAlmostEqual(c[1][1], 40 / 500 * 100)
        self.assertAlmostEqual(logbook.average_l100(es), 90 / 1100 * 100)
        self.assertEqual(logbook.work_out(40, 23.5, None), (40, 23.5, 940.0))
        self.assertEqual(logbook.work_out(40, None, 940), (40, 23.5, 940))
        self.assertEqual(logbook.work_out(None, 23.5, 940), (40.0, 23.5, 940))

    def test_months(self):
        es = [trip(ms(2026, 5, 3, 8), 100, business=True), trip(ms(2026, 5, 4, 8), 50), fuel(ms(2026, 5, 5, 8), 1500, 40),
              trip(ms(2026, 4, 3, 8), 10), fuel(ms(2026, 4, 4, 8), 1000, 30)]
        rows = logbook.months(es)
        self.assertEqual([r["month"] for r in rows], ["2026-05", "2026-04"])
        self.assertEqual((rows[0]["km"], rows[0]["business_km"], rows[0]["fills"]), (150, 100, 1))
        self.assertAlmostEqual(rows[0]["l100"], 8)                     # 40 L over 500 km
        self.assertAlmostEqual(rows[0]["cost_per_km"], 0.08 * 23)
        self.assertIsNone(rows[1]["cost_per_km"])

    # ---- service reminders ----

    def test_reminders_by_distance_or_time_whichever_first(self):
        now = ms(2026, 11, 1, 12)
        rem = logbook.make("reminder", ms(2026, 1, 10, 8))
        rem.update({"what": "Oil change", "every_km": 10000, "every_months": 12, "from_odometer": 100000})
        es = [rem, reading(ms(2026, 10, 1, 8), 109300)]
        d = logbook.reminders(es, now)[0]
        self.assertAlmostEqual(d["km_left"], 700)
        self.assertEqual(d["days_left"], (ms(2027, 1, 10, 8) - now) // 86400000)
        self.assertTrue(d["soon"] and not d["overdue"])
        self.assertEqual(logbook.due_text(d), "in 700 km")
        # done again (a service of that name, any case): counted from there
        es.append(reading(ms(2026, 10, 2, 8), 109400, "service", what="oil change "))
        d = logbook.reminders(es, now)[0]
        self.assertAlmostEqual(d["km_left"], 10000 - 0)
        self.assertFalse(d["soon"])
        self.assertEqual(logbook.due_text(d), "in 11 months")       # the time runs out first now

    def test_a_reminder_by_time_only_and_overdue(self):
        now = ms(2026, 11, 1, 12)
        rem = logbook.make("reminder", ms(2025, 10, 1, 8))
        rem.update({"what": "Licence renewal", "every_months": 12})
        d = logbook.reminders([rem], now)[0]
        self.assertIsNone(d["km_left"])
        self.assertTrue(d["overdue"])
        self.assertEqual(logbook.due_text(d), "31 days overdue")
        # by distance with no odometer at all: nothing to measure it by yet
        rem2 = dict(logbook.make("reminder", now), what="Tyres", every_km=10000)
        self.assertEqual([x["what"] for x in logbook.reminders([rem, rem2], now)], ["Licence renewal"])
        with self.assertRaises(ValueError):
            logbook.check(dict(logbook.make("reminder", now), what="Nothing"))
        self.assertEqual(logbook.months([rem]), [])

    # ---- SARS ----

    def test_sars_year_runs_march_to_february(self):
        es = [reading(ms(2026, 2, 20, 8), 20000),
              trip(ms(2026, 2, 28, 12), 100, business=True, purpose="Last year's"),
              trip(ms(2026, 3, 1, 9), 200, business=True, purpose="Client & partner visit"),
              trip(ms(2026, 3, 2, 9), 50),
              trip(ms(2026, 3, 3, 9), 30, business=True),
              reading(ms(2026, 3, 10, 8), 20380)]
        r = logbook.sars(es, 2027)
        self.assertEqual((str(r["start"]), str(r["end"])), ("2026-03-01", "2027-02-28"))
        self.assertEqual([t["purpose"] for t in r["trips"]], ["Client & partner visit", ""])
        self.assertAlmostEqual(r["business_km"], 230)
        self.assertAlmostEqual(r["opening"], 20100)
        self.assertAlmostEqual(r["closing"], 20380)
        self.assertAlmostEqual(r["private_km"], 280 - 230)
        self.assertAlmostEqual(r["trips"][0]["odo_start"], 20100)
        self.assertAlmostEqual(r["trips"][0]["odo_end"], 20300)
        self.assertEqual(r["no_purpose"], 1)
        self.assertEqual(logbook.current_tax_year(datetime.date(2026, 2, 28)), 2026)
        self.assertEqual(logbook.current_tax_year(datetime.date(2026, 3, 1)), 2027)
        html = logbook.sars_html(r, "Toyota Corolla 1.6, CA 123-456")
        self.assertIn("Client &amp; partner visit", html)
        self.assertIn("20 380 km", html)
        path = logbook.sars_csv(r, os.path.join(self.tmp, "s.csv"), "Toyota")
        with open(path) as f:
            text = f.read()
        self.assertIn("Opening odometer,20 100", text)
        self.assertIn("Client & partner visit", text)

    def test_export_csv(self):
        es = [trip(ms(2026, 5, 3, 8), 12.5, business=True, purpose="Visit"), fuel(ms(2026, 5, 5, 8), 1000, 40)]
        path = logbook.export_csv(es, os.path.join(self.tmp, "all.csv"))
        with open(path) as f:
            lines = f.read().splitlines()
        self.assertTrue(lines[0].startswith("date,type,from,to,km,business,purpose,odometer,litres"))
        self.assertIn(",trip,Home,Acme & Sons,12.5,yes,Visit,", lines[1])
        self.assertIn(",fuel,", lines[2])


if __name__ == "__main__":
    unittest.main()
