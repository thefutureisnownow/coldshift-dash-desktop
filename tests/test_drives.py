import datetime
import os
import shutil
import tempfile
import unittest
from unittest import mock

from dashsync import drives, recordings, thumbs


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def row(key):
    """A Recordings list row (as group_items makes them) for one file."""
    d = recordings.describe(key)
    item = dict(d, key=key, size=1, pulled=True, pulled_before=False, busy=False, on_card=True)
    return {"id": (d["group"], d["base"]), "when": d["when"], "kind": d["kind"], "items": [item]}


def epoch(*a):
    return datetime.datetime(*a).timestamp()


class DrivesTest(unittest.TestCase):
    def setUp(self):
        self.dest = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dest, ignore_errors=True)

    def ids(self, ds):
        return [[r["id"][1] for r in d["rows"]] for d in ds]

    def test_a_trip_and_its_clips_make_one_drive_and_a_gap_starts_another(self):
        rows = [row(k) for k in ("clips/000001_20261115_100000.mp4", "trips/trip_20261115_100000.csv",
                                 "clips/000002_20261115_100301.mp4", "clips/000003_20261115_100602.mp4",
                                 # 20 minutes later: another outing, its trip log a few seconds after the clip
                                 "clips/000004_20261115_103000.mp4", "trips/trip_20261115_103005.csv",
                                 "sound/sound_20261115_103100.wav")]
        ds = drives.group(rows, self.dest)
        self.assertEqual(self.ids(ds), [["sound_20261115_103100", "trip_20261115_103005", "000004_20261115_103000"],
                                        ["000003_20261115_100602", "000002_20261115_100301", "trip_20261115_100000",
                                         "000001_20261115_100000"]])
        self.assertEqual(ds[1]["start"], epoch(2026, 11, 15, 10, 0, 0))
        self.assertEqual(ds[1]["end"], epoch(2026, 11, 15, 10, 6, 2) + drives.CLIP_S)

    def test_a_new_trip_soon_after_the_last_is_a_drive_of_its_own(self):
        rows = [row(k) for k in ("trips/trip_20261115_100000.csv", "clips/000001_20261115_100000.mp4",
                                 "trips/trip_20261115_100400.csv", "clips/000002_20261115_100400.mp4")]
        self.assertEqual(len(drives.group(rows, self.dest)), 2)

    def test_what_is_here_says_how_long_it_ran(self):
        # the trip log here ends 40 minutes in: a clip 30 minutes after its start is still that drive
        t0 = epoch(2026, 11, 15, 10, 0, 0)
        write(os.path.join(self.dest, "trips", "trip_20261115_100000.csv"),
              ("time_ms,rpm\n%d,900\n%d,950\n" % (t0 * 1000, (t0 + 2400) * 1000)).encode())
        rows = [row("trips/trip_20261115_100000.csv"), row("clips/000009_20261115_103000.mp4")]
        self.assertEqual(len(drives.group(rows, self.dest)), 1)
        # without it the gap is too long
        os.remove(os.path.join(self.dest, "trips", "trip_20261115_100000.csv"))
        self.assertEqual(len(drives.group(rows, self.dest)), 2)

    def test_undated_rows_come_last(self):
        rows = [row("trips/odd.csv"), row("clips/000001_20261115_100000.mp4")]
        ds = drives.group(rows, self.dest)
        self.assertEqual((ds[-1]["start"], self.ids(ds)[-1]), (None, ["odd"]))

    def test_readings_between(self):
        t0 = epoch(2026, 11, 15, 10, 0, 0)
        write(os.path.join(self.dest, "trips", "trip_20261115_100000.csv"),
              ("time_ms,lat,lon,speed_ms,rpm,obd_kmh,throttle_pct\n"
               "%d,1,2,10,900,,15\n%d,1,2,10,3000,40,60\n%d,1,2,10,950,0,14\n"
               % (t0 * 1000, (t0 + 1) * 1000, (t0 + 600) * 1000)).encode())
        r = drives.readings_between(self.dest, t0, t0 + 10)
        self.assertEqual(r, [(t0, 900.0, 36.0, 15.0), (t0 + 1, 3000.0, 40.0, 60.0)])
        self.assertEqual(drives.readings_between(self.dest, t0 + 3600, t0 + 3700), [])
        self.assertEqual(drives.clip_start("/x/000002_20261115_100000.mp4"), t0)


class ThumbsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"DASHSYNC_CACHE": os.path.join(self.tmp, "cache")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_photo_is_made_small_once_and_again_when_it_changes(self):
        from PIL import Image
        src = os.path.join(self.tmp, "interior_20261115_100000.jpg")
        Image.new("RGB", (1600, 1200), "red").save(src)
        p = thumbs.make(src)
        with Image.open(p) as im:
            self.assertEqual(im.size, (thumbs.WIDTH, 120))
        self.assertEqual(thumbs.cached(src), p)
        Image.new("RGB", (800, 600), "blue").save(src)
        os.utime(src, ns=(1, 1))
        self.assertIsNone(thumbs.cached(src))

    @unittest.skipUnless(thumbs.ffmpegtool.path("ffmpeg"), "needs ffmpeg")
    def test_a_video_still(self):
        import subprocess
        src = os.path.join(self.tmp, "000001_20261115_100000.mp4")
        subprocess.run([thumbs.ffmpegtool.path("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                        "testsrc=size=320x180:rate=30:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", src],
                       check=True)
        p = thumbs.make(src)
        self.assertTrue(p and os.path.getsize(p) > 0)

    def test_a_video_without_ffmpeg_is_left_to_the_app(self):
        src = os.path.join(self.tmp, "000001_20261115_100000.mp4")
        write(src, b"not really")
        with mock.patch("dashsync.ffmpegtool.path", return_value=None):
            self.assertFalse(thumbs.can_make(src))
            self.assertIsNone(thumbs.make(src))


if __name__ == "__main__":
    unittest.main()
