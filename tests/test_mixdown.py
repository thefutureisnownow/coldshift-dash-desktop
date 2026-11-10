import os
import shutil
import subprocess
import tempfile
import unittest

from dashsync import mixdown

FFMPEG = mixdown.tool("ffmpeg")


def make_clip(path, seconds=2, left_hz=440, right_hz=None, video=True):
    """A small test clip: a test picture, and a tone on the left (and another on the right, or one channel only)."""
    cmd = [FFMPEG, "-v", "error", "-y"]
    if video:
        cmd += ["-f", "lavfi", "-i", "testsrc=size=160x120:rate=30:duration=%d" % seconds]
    cmd += ["-f", "lavfi", "-i", "sine=frequency=%d:duration=%d" % (left_hz, seconds)]
    if right_hz:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=%d:duration=%d" % (right_hz, seconds)]
        a = 1 if video else 0
        cmd += ["-filter_complex", "[%d:a][%d:a]join=inputs=2:channel_layout=stereo[a]" % (a, a + 1),
                "-map", "[a]"] + (["-map", "0:v"] if video else [])
    if video:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", "128k", path]
    subprocess.run(cmd, check=True)


def peak_db(path, af):
    r = subprocess.run([FFMPEG, "-v", "info", "-i", path, "-af", af + ",astats=measure_perchannel=0:measure_overall=Peak_level",
                        "-f", "null", "-"], capture_output=True, text=True)
    line = [ln for ln in r.stderr.splitlines() if "Peak level dB" in ln][-1]
    return float(line.rsplit(":", 1)[1])


class GainsTest(unittest.TestCase):
    def test_gains(self):
        self.assertEqual(mixdown.gains(0), (1.0, 1.0))
        self.assertEqual(mixdown.gains(-1), (1.0, 0.0))
        self.assertEqual(mixdown.gains(1), (0.0, 1.0))
        self.assertEqual(mixdown.gains(0.5), (0.5, 1.0))
        self.assertEqual(mixdown.gains(9), (0.0, 1.0))

    def test_filter(self):
        self.assertEqual(mixdown.mix_filter(2, -0.5, 3),
                         "pan=stereo|c0=1.000*c0+0.500*c1|c1=1.000*c0+0.500*c1,volume=3.00dB")
        self.assertEqual(mixdown.mix_filter(1, 0.7), "pan=stereo|c0=c0|c1=c0,volume=0.00dB")

    def test_level(self):
        # toward -14 LUFS, but the loudest peak stays under -1 dBTP
        self.assertAlmostEqual(mixdown.level_gain(-30, -20), 16)
        self.assertAlmostEqual(mixdown.level_gain(-30, -8), 7)
        self.assertAlmostEqual(mixdown.level_gain(-30, -8, normalize=False), 0)
        self.assertAlmostEqual(mixdown.level_gain(-10, 2, normalize=False), -3)
        self.assertAlmostEqual(mixdown.level_gain(None, None), 0)

    def test_name(self):
        self.assertEqual(mixdown.default_name(["/a/000001_x.mp4"]), "000001_x.mp4")
        self.assertEqual(mixdown.default_name(["/a/1.mp4", "/a/2.mp4", "/a/3.mp4"]), "1 to 3.mp4")


@unittest.skipUnless(FFMPEG and mixdown.tool("ffprobe"), "needs ffmpeg")
class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = os.path.join(self.tmp, "000001_20261110_121217.mp4")
        self.b = os.path.join(self.tmp, "000002_20261110_121219.mp4")
        make_clip(self.a, left_hz=440, right_hz=1000)
        make_clip(self.b, left_hz=440, right_hz=1000)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_one_clip(self):
        out = os.path.join(self.tmp, "Exports", "one.mp4")
        seen = []
        r = mixdown.export([self.a], out, balance=-1, progress=lambda d, t: seen.append((d, t)))
        info = mixdown.probe(out)
        self.assertEqual(info["channels"], 2)
        self.assertTrue(info["video"])
        self.assertAlmostEqual(info["duration"], 2, delta=0.2)
        self.assertTrue(seen and seen[-1][0] == seen[-1][1])
        self.assertLessEqual(r["peak"] + r["gain_db"], mixdown.CEILING_DBTP + 0.01)
        # the same mix on both channels, exactly
        self.assertEqual(peak_db(out, "pan=mono|c0=c0-c1"), float("-inf"))
        # balance -1 keeps only the left tone: nothing near 1 kHz
        self.assertLess(peak_db(out, "pan=mono|c0=c0,bandpass=f=1000:w=50"), -40)
        self.assertGreater(peak_db(out, "pan=mono|c0=c0,bandpass=f=440:w=50"), -20)
        self.assertFalse(os.path.exists(out + ".part.mp4"))

    def test_joined(self):
        out = os.path.join(self.tmp, "joined.mp4")
        mixdown.export([self.a, self.b], out, balance=0.0)
        self.assertAlmostEqual(mixdown.probe(out)["duration"], 4, delta=0.3)

    def test_mono_clip(self):
        mono = os.path.join(self.tmp, "mono.mp4")
        make_clip(mono)
        out = os.path.join(self.tmp, "mono-out.mp4")
        mixdown.export([mono], out, balance=1)
        self.assertEqual(mixdown.probe(out)["channels"], 2)
        self.assertGreater(peak_db(out, "pan=mono|c0=c1"), -20)

    def test_mixed_channels_refused(self):
        mono = os.path.join(self.tmp, "mono.mp4")
        make_clip(mono)
        with self.assertRaises(mixdown.MixError):
            mixdown.export([self.a, mono], os.path.join(self.tmp, "x.mp4"))

    def test_preview(self):
        wav = mixdown.preview(self.a, balance=1, seconds=1)
        try:
            self.assertTrue(os.path.getsize(wav) > 1000)
        finally:
            os.remove(wav)


if __name__ == "__main__":
    unittest.main()
