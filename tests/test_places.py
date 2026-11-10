import json
import os
import shutil
import tempfile
import unittest

from dashsync import places
from dashsync.transport import FolderTarget

PLACES = {"version": 1, "places": [
    {"kind": "home", "name": "Home", "sub": "York Street, George", "lat": -33.958, "lon": 22.448, "time": 1},
    {"kind": "saved", "name": "Engen", "sub": "Fuel", "lat": -33.962, "lon": 22.46, "time": 2},
    {"kind": "recent", "name": "Knysna", "sub": "", "lat": -34.035, "lon": 23.047, "time": 3}]}


class PlacesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.card = os.path.join(self.tmp, "card")
        self.ws = os.path.join(self.tmp, "ws")
        os.makedirs(self.card)
        self.target = FolderTarget(self.card)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def phone_writes(self, data):
        path = os.path.join(self.card, *places.PHONE.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_nothing_on_the_phone_yet(self):
        self.assertIsNone(places.on_phone(self.target))
        self.assertIsNone(places.backup(self.target, self.ws)["places"])

    def test_backup_keeps_the_previous_copy(self):
        self.phone_writes(PLACES)
        r = places.backup(self.target, self.ws)
        self.assertTrue(r["changed"])
        self.assertEqual(places.describe(r["places"]), "Home, no Work, 1 saved, 1 recent")
        self.assertFalse(places.backup(self.target, self.ws)["changed"])
        more = dict(PLACES, places=PLACES["places"] + [{"kind": "work", "name": "Work", "lat": -34, "lon": 22, "time": 4}])
        self.phone_writes(more)
        self.assertTrue(places.backup(self.target, self.ws)["changed"])
        self.assertEqual(len(places.read(os.path.join(self.ws, "places.previous.json"))), 3)
        self.assertEqual(len(places.read(places.backup_path(self.ws))), 4)

    def test_restore_puts_the_backup_where_the_app_looks(self):
        self.phone_writes(PLACES)
        places.backup(self.target, self.ws)
        r = places.restore(self.target, self.ws)
        self.assertEqual(len(r["places"]), 3)
        self.assertIsNone(r["app"])               # a card in a reader: the app merges it when it starts
        with open(os.path.join(self.card, "coldshift.dash", "places.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), PLACES)

    def test_a_broken_file_is_not_backed_up(self):
        self.phone_writes({"places": [{"kind": "castle", "lat": 1, "lon": 2}]})
        with self.assertRaises(ValueError):
            places.backup(self.target, self.ws)
        self.assertFalse(os.path.exists(places.backup_path(self.ws)))


class AddPlacesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, "ws")
        self.card = os.path.join(self.tmp, "card")
        os.makedirs(self.card)
        self.target = FolderTarget(self.card)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def phone_has(self, plist):
        path = os.path.join(self.card, *places.PHONE.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "places": plist}, f)

    def test_coordinates_as_people_paste_them(self):
        self.assertEqual(places.parse_coords("-33.92490, 18.42410"), (-33.92490, 18.42410))
        self.assertEqual(places.parse_coords("33.92490 S, 18.42410 E"), (-33.92490, 18.42410))
        self.assertEqual(places.parse_coords("51.5 22.4"), (51.5, 22.4))
        for bad in ("york street", "95, 10", "-33.9"):
            with self.assertRaises(ValueError):
                places.parse_coords(bad)

    def test_added_places_wait_until_synced_and_survive_a_sync_to_pc(self):
        self.phone_has([{"kind": "home", "name": "Home", "lat": -34.0, "lon": 22.0}])
        places.backup(self.target, self.ws)
        places.add(self.ws, "saved", "Granny's", -33.95, 22.47)
        places.add(self.ws, "home", "", -33.96, 22.46)             # replaces the phone's Home here
        r = places.backup(self.target, self.ws)                    # the phone has not got them yet
        names = sorted((p["kind"], p["name"]) for p in r["places"])
        self.assertEqual(names, [("home", "Home"), ("saved", "Granny's")])
        self.assertEqual([p["lat"] for p in r["places"] if p["kind"] == "home"], [-33.96])
        places.restore(self.target, self.ws)                       # on the card: no longer waiting
        self.assertFalse(any(p.get("waiting") for p in places.read(places.backup_path(self.ws))))
        with open(os.path.join(self.card, "coldshift.dash", "places.json"), encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["places"]), 2)

    def test_remove_and_checks(self):
        places.add(self.ws, "saved", "A", 1, 2)
        places.add(self.ws, "saved", "B", 3, 4)
        self.assertEqual([p["name"] for p in places.remove(self.ws, 0)], ["B"])
        with self.assertRaises(ValueError):
            places.add(self.ws, "saved", "", 1, 2)
        with self.assertRaises(ValueError):
            places.add(self.ws, "recent", "X", 1, 2)


if __name__ == "__main__":
    unittest.main()
