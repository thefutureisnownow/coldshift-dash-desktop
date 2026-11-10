import json
import os
import shutil
import tempfile
import unittest

from dashsync import layout, track
from dashsync.transport import FolderTarget

# a 600 m straight segment heading north
POINTS = [[-34.0 + i * 0.054 / 1000, 22.5] for i in range(101)]


def run(start, speed, mark=0, length=600.0):
    t = [i * 1.0 for i in range(int(length / speed) + 1)] + [length / speed]
    return {"version": 1, "segment": "seg-1", "start": start, "time_ms": int(length / speed * 1000), "lap": 0,
            "mark": mark, "t": t, "d": [min(x * speed, length) for x in t], "speed": [speed] * len(t)}


class TrackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.v = os.path.join(self.tmp, "vehicle")
        self.card = os.path.join(self.tmp, "card")
        phone = os.path.join(self.card, *track.PHONE.split("/"))
        os.makedirs(os.path.join(phone, "segments"))
        os.makedirs(os.path.join(phone, "runs", "seg-1"))
        with open(os.path.join(phone, "segments", "seg-1.json"), "w") as f:
            json.dump({"version": 1, "id": "seg-1", "name": "Straight", "created": 1, "points": POINTS}, f)
        for name, r in (("1000-0.json", run(1000, 20)), ("2000-0.json", run(2000, 24, mark=7))):
            with open(os.path.join(phone, "runs", "seg-1", name), "w") as f:
                json.dump(r, f)
        self.target = FolderTarget(self.card)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sync_to_pc_copies_once(self):
        self.assertEqual(track.sync_to_pc(self.target, self.v), {"segments": 1, "runs": 2})
        self.assertEqual(track.sync_to_pc(self.target, self.v), {"segments": 0, "runs": 0})
        s = track.segments(self.v)[0]
        self.assertEqual((s["name"], s["lap"], s["runs"], s["best_ms"]), ("Straight", False, 2, 25000))
        self.assertAlmostEqual(s["length"], 600, delta=2)

    def test_a_name_changed_here_survives_a_sync_to_pc_and_goes_to_the_card(self):
        track.sync_to_pc(self.target, self.v)
        track.rename(self.v, "seg-1", "Main straight")
        track.mark_renamed(self.v, "seg-1")
        # the phone's copy changes meanwhile (a new size), and is copied again
        phone = os.path.join(self.card, *track.PHONE.split("/"), "segments", "seg-1.json")
        with open(phone, "w") as f:
            json.dump({"version": 1, "id": "seg-1", "name": "Straight ", "created": 1, "points": POINTS}, f)
        track.sync_to_pc(self.target, self.v)
        self.assertEqual(track.segments(self.v)[0]["name"], "Main straight")
        r = track.sync_to_card(self.target, self.v)
        self.assertEqual((r["segments"], r["copied"]), (1, 1))
        with open(os.path.join(self.card, *track.SHARED.split("/"), "seg-1.json")) as f:
            self.assertEqual(json.load(f)["name"], "Main straight")

    def test_export_import_and_gpx(self):
        track.sync_to_pc(self.target, self.v)
        path = track.export_segment(self.v, "seg-1", os.path.join(self.tmp, "s.segment.json"))
        sid = track.import_segment(self.v, path)
        self.assertNotEqual(sid, "seg-1")
        with open(os.path.join(self.tmp, "s.gpx"), "w") as f:
            f.write(track.segment_gpx(track.segment(self.v, "seg-1")))
        gid = track.import_segment(self.v, os.path.join(self.tmp, "s.gpx"))
        self.assertEqual(len(track.segment(self.v, gid)["points"]), len(POINTS))
        self.assertEqual(track.segment(self.v, gid)["name"], "Straight")
        with self.assertRaises(ValueError):
            bad = os.path.join(self.tmp, "x.json")
            with open(bad, "w") as f:
                json.dump({"hello": 1}, f)
            track.import_segment(self.v, bad)

    def test_compare_over_distance(self):
        a, b = run(1, 20), run(2, 24)
        rows = track.compare(a, b, 600, step=100)
        self.assertAlmostEqual(rows[-1][1], 600 / 24 - 600 / 20, places=2)     # b ahead by 5 s at the finish
        self.assertAlmostEqual(rows[3][1], 300 / 24 - 300 / 20, places=2)
        self.assertAlmostEqual(rows[3][3], 24 * 3.6, places=1)

    def test_share_run_with_its_clip(self):
        track.sync_to_pc(self.target, self.v)
        rec = os.path.join(self.tmp, "recordings")
        os.makedirs(os.path.join(rec, "marks"))
        with open(os.path.join(rec, "marks", "mark_0007_20261101_093427.mp4"), "wb") as f:
            f.write(b"video")
        r = [x for x in track.runs(self.v, "seg-1") if x.get("mark") == 7][0]
        folder, has_clip = track.share_run(self.v, "seg-1", r["file"], os.path.join(self.tmp, "out"), rec)
        self.assertTrue(has_clip)
        self.assertEqual(sorted(os.listdir(folder)), ["about.txt", "clip.mp4", "run.csv", "run.gpx", "segment.gpx"])
        with open(os.path.join(folder, "run.csv")) as f:
            self.assertEqual(f.readline().strip(), "time_s,distance_m,speed_kmh,lat,lon")
        other = [x for x in track.runs(self.v, "seg-1") if not x.get("mark")][0]
        self.assertFalse(track.share_run(self.v, "seg-1", other["file"], os.path.join(self.tmp, "out"), rec)[1])


if __name__ == "__main__":
    unittest.main()
