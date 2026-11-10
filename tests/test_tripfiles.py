import datetime
import os
import shutil
import tempfile
import unittest
import wave

from dashsync import tripfiles


def ms(h, m, s=0):
    return int(datetime.datetime(2026, 11, 4, h, m, s).timestamp() * 1000)


class TripFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dest = os.path.join(self.tmp, "recordings")
        self.vehicle = os.path.join(self.tmp, "car")

        def put(rel, data=b"x"):
            p = os.path.join(self.dest, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
            return p

        # a clip from 10:00 whose subtitles run to 10:04:59: into the trip that starts at 10:02
        put("clips/000001_20261104_100000.mp4")
        put("clips/000001_20261104_100000.srt", b"300\n00:04:59,000 --> 00:04:59,950\n2026-11-04 10:04:59\n\n")
        # a clip after the trip, and an interior shot before it
        put("clips/000002_20261104_103000.mp4")
        put("interior/interior_20261104_093000.jpg")
        # the dashcam's trip log from 09:55, its last row at 10:10
        put("trips/trip_20261104_095500.csv", ("time_ms,lat,lon\n%d,1,2\n%d,1,2\n" % (ms(9, 55), ms(10, 10))).encode())
        # a sound recording at 10:05, 2 s, with named channels
        p = put("sound/sound_20261104_100500.wav")
        with wave.open(p, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(b"\0\0\0\0" * 96000)
        put("sound/sound_20261104_100500.csv", b"# started\n# channels: left = Engine; right = Exhaust\nms\n")
        # the trip's route
        os.makedirs(os.path.join(self.vehicle, "log", "routes"))
        with open(os.path.join(self.vehicle, "log", "routes", "t1.csv"), "w") as f:
            f.write("%d,-34.03,23.05,10.0\n%d,-34.04,23.06,12.0\n" % (ms(10, 2), ms(10, 19)))
        self.trip = {"id": "t1", "type": "trip", "time": ms(10, 2), "end": ms(10, 20), "dist_m": 12300, "max": 25,
                     "from": {"name": "Home"}, "to": {"name": "Sedgefield / Lagoon"}}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_matching(self):
        got = {(r["group"], r["base"]) for r in tripfiles.matching(self.dest, self.trip)}
        self.assertEqual(got, {("clips", "000001_20261104_100000"), ("trips", "trip_20261104_095500"),
                               ("sound", "sound_20261104_100500")})

    def test_gather(self):
        r = tripfiles.gather(self.vehicle, self.dest, self.trip, log=lambda s: None)
        self.assertTrue(r["folder"].endswith("2026-11-04 1002 Home to Sedgefield Lagoon"))
        self.assertEqual((r["copied"], r["had"], r["route"]), (5, 0, 2))
        for rel in ("clips/000001_20261104_100000.srt", "sound/sound_20261104_100500.wav", "route.csv", "route.gpx",
                    "trip.txt"):
            self.assertTrue(os.path.exists(os.path.join(r["folder"], *rel.split("/"))), rel)
        self.assertFalse(os.path.exists(os.path.join(r["folder"], "interior")))
        with open(os.path.join(r["folder"], "trip.txt"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Sound (Engine / Exhaust)", text)
        self.assertIn("12.3 km", text)
        again = tripfiles.gather(self.vehicle, self.dest, self.trip, log=lambda s: None)
        self.assertEqual((again["copied"], again["had"]), (0, 5))

    def test_nothing_copied_yet(self):
        empty = os.path.join(self.tmp, "none")
        r = tripfiles.gather(self.vehicle, empty, self.trip, log=lambda s: None)
        with open(os.path.join(r["folder"], "trip.txt"), encoding="utf-8") as f:
            self.assertIn("Sync to PC", f.read())


if __name__ == "__main__":
    unittest.main()
