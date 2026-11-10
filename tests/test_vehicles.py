import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from dashsync import backup, layout, paths, vehicles
from dashsync.transport import FolderTarget


class VehiclesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"DASHSYNC_CONFIG": os.path.join(self.tmp, "config"),
                                                "DASHSYNC_CACHE": os.path.join(self.tmp, "cache")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_settings_from_before_vehicles_become_the_first_vehicle_in_place(self):
        ws = os.path.join(self.tmp, "ws")
        os.makedirs(ws)
        paths.save_global({"workspace": ws, "map_region": "africa/za.map", "phone": "abc", "adb": {"path": "/x"}})
        cfg = paths.load_config()
        self.assertEqual((cfg["workspace"], cfg["map_region"], cfg["phone"], cfg["adb"]), (ws, "africa/za.map", "abc", {"path": "/x"}))
        g = paths.global_config()
        self.assertNotIn("map_region", g)
        self.assertEqual(json.load(open(os.path.join(ws, "vehicle.json")))["phone"], "abc")

    def test_each_vehicle_keeps_its_own_settings(self):
        a = vehicles.create("Peppermint Crisp", os.path.join(self.tmp, "a"))
        cfg = paths.load_config()
        cfg["map_region"], cfg["phone"], cfg["adb"] = "africa/za.map", "phone-a", {"path": "/adb"}
        paths.save_config(cfg)
        b = vehicles.create("Lemon Drizzle")
        self.assertEqual(b["folder"], os.path.join(self.tmp, "lemon-drizzle"))     # beside the first
        cfg = paths.load_config()
        self.assertEqual((cfg.get("map_region"), cfg.get("phone"), cfg["adb"]), (None, None, {"path": "/adb"}))
        cfg["phone"] = "phone-b"
        paths.save_config(cfg)
        vehicles.select(a["id"])
        self.assertEqual(paths.load_config()["phone"], "phone-a")
        self.assertEqual(paths.load_config()["workspace"], a["folder"])
        vehicles.rename(b["id"], "Lemon Drizzle GT")
        self.assertEqual([v["name"] for v in vehicles.all()], ["Peppermint Crisp", "Lemon Drizzle GT"])
        vehicles.forget(a["id"])
        self.assertEqual(vehicles.current()["id"], b["id"])
        self.assertTrue(os.path.isdir(a["folder"]))                       # the files stay
        self.assertEqual(vehicles.add(a["folder"])["name"], "Peppermint Crisp")
        with self.assertRaises(ValueError):
            vehicles.create("Again", a["folder"])

    def test_backup_and_restore_of_what_only_the_phone_has(self):
        v = vehicles.create("Car", os.path.join(self.tmp, "car"))["folder"]
        card = os.path.join(self.tmp, "card")
        app = os.path.join(card, *layout.APP_DATA.split("/"))
        os.makedirs(app)
        with open(os.path.join(app, "settings.json"), "w") as f:
            json.dump({"brightness": 90, "voice": "angie"}, f)
        with open(os.path.join(app, "places.json"), "w") as f:
            json.dump({"version": 1, "places": [{"kind": "home", "name": "Home", "lat": -34.0, "lon": 22.4}]}, f)
        target = FolderTarget(card)
        r = backup.backup(target, v)
        self.assertEqual((r["settings"]["brightness"], sorted(r["changed"])), (90, ["places", "settings"]))
        self.assertEqual(backup.backup(target, v)["changed"], [])
        with open(os.path.join(app, "settings.json"), "w") as f:
            json.dump({"brightness": 200}, f)
        backup.backup(target, v)
        self.assertTrue(os.path.exists(os.path.join(v, "app-settings.previous.json")))
        with mock.patch.object(backup.maps, "chosen", return_value=None):
            out = backup.restore(target, v)
        self.assertEqual(out["places and settings"], "places, settings")
        self.assertEqual(json.load(open(os.path.join(card, "coldshift.dash", "settings.json")))["brightness"], 200)
        self.assertTrue(os.path.exists(os.path.join(card, "coldshift.dash", "places.json")))
        self.assertEqual(out["map"], "no region chosen yet")


if __name__ == "__main__":
    unittest.main()
