import datetime
import os
import shutil
import tempfile
import unittest

from dashsync import layout, recordings
from dashsync.transport import FolderTarget


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class RecordingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.card_root = os.path.join(self.tmp, "card")
        self.dest = os.path.join(self.tmp, "recordings")
        self.cam = os.path.join(self.card_root, *layout.DASHCAM_DIR.split("/"))
        write(self.cam + "/000001_20261101_101500.mp4", b"v" * 1000)
        write(self.cam + "/000001_20261101_101500.srt", b"s" * 10)
        write(self.cam + "/000001_20261101_101500.gcsv", b"g" * 20)
        write(self.cam + "/000002_20261101_102000_L.mp4", b"L" * 500)
        write(self.cam + "/000002_20261101_102000_L.srt", b"l" * 10)
        write(self.cam + "/marks/mark_0001_20261101_101700.json", b"{}")
        write(self.cam + "/trips/trip_20261101_101500.csv", b"t,1\n")
        self.card = FolderTarget(self.card_root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_describe(self):
        d = recordings.describe("clips/000002_20261101_102000_L.srt")
        self.assertEqual((d["kind"], d["base"], d["locked"]), ("clip", "000002_20261101_102000_L", True))
        self.assertEqual(d["when"], datetime.datetime(2026, 11, 1, 10, 20, 0))
        m = recordings.describe("marks/mark_0001_20261101_101700.json")
        self.assertEqual((m["kind"], m["locked"]), ("mark", False))
        self.assertIsNone(recordings.describe("trips/odd.csv")["when"])
        i = recordings.describe("interior/interior_20261104_102736.jpg")
        self.assertEqual((i["kind"], i["when"].hour, i["locked"]), ("interior", 10, False))
        s = recordings.describe("sound/sound_20261104_141502.csv")
        os.makedirs(os.path.join(self.dest, "sound"))
        with open(os.path.join(self.dest, "sound", "sound_20261104_141502.csv"), "w", encoding="utf-8") as f:
            f.write("# started 2026-11-04T14:15:02.000+0200, 48000 Hz, 2 channels\n# channels: left = Engine; right = \n")
        self.assertEqual(recordings.sound_channels(self.dest, "sound_20261104_141502"), ["Engine", ""])
        self.assertEqual(recordings.sound_channels(self.dest, "sound_missing"), [])
        self.assertEqual((s["kind"], s["base"], s["when"].minute), ("sound", "sound_20261104_141502", 15))

    def test_status_then_pull_then_status(self):
        st = recordings.status([self.card], self.dest)
        self.assertEqual(len(st["items"]), 7)
        self.assertFalse(any(i["pulled"] for i in st["items"]))
        seen = []
        r = recordings.pull([self.card], self.dest, log=lambda m: None, progress=lambda *a: seen.append(a))
        self.assertEqual(r["pulled"], 7)
        self.assertEqual(seen[-1][:2], (7, 7))
        self.assertEqual(seen[-1][2], seen[-1][3])          # all bytes done
        self.assertTrue(all(i["pulled"] for i in recordings.status([self.card], self.dest)["items"]))

    def test_delete_pulled_keeps_locked_clips_and_unpulled_files(self):
        recordings.pull([self.card], self.dest, log=lambda m: None)
        write(self.cam + "/000003_20261101_102500.mp4", b"n" * 300)          # recorded after the pull
        r = recordings.delete_pulled([self.card], self.dest, log=lambda m: None)
        self.assertEqual((r["deleted"], r["kept_locked"], r["not_pulled"]), (5, 2, 1))
        self.assertEqual(r["freed"], 1000 + 10 + 20 + 2 + 4)
        left = sorted(os.listdir(self.cam))
        self.assertIn("000002_20261101_102000_L.mp4", left)
        self.assertIn("000003_20261101_102500.mp4", left)
        self.assertNotIn("000001_20261101_101500.mp4", left)
        r = recordings.delete_pulled([self.card], self.dest, keep_locked=False, log=lambda m: None)
        self.assertEqual(r["deleted"], 2)

    def test_file_changed_since_the_pull_stays_on_the_card(self):
        recordings.pull([self.card], self.dest, log=lambda m: None)
        write(self.cam + "/trips/trip_20261101_101500.csv", b"t,1\nt,2\n")    # the trip log grew
        r = recordings.delete_pulled([self.card], self.dest, log=lambda m: None)
        self.assertTrue(os.path.exists(self.cam + "/trips/trip_20261101_101500.csv"))
        self.assertEqual(r["not_pulled"], 1)

    def test_local_copy_missing_means_not_deleted(self):
        recordings.pull([self.card], self.dest, log=lambda m: None)
        os.remove(os.path.join(self.dest, "clips", "000001_20261101_101500.mp4"))
        recordings.delete_pulled([self.card], self.dest, log=lambda m: None)
        self.assertTrue(os.path.exists(self.cam + "/000001_20261101_101500.mp4"))
        st = {i["key"]: i for i in recordings.status([self.card], self.dest)["items"]}
        self.assertFalse(st["clips/000001_20261101_101500.mp4"]["pulled"])
        self.assertTrue(st["clips/000001_20261101_101500.mp4"]["pulled_before"])


if __name__ == "__main__":
    unittest.main()
