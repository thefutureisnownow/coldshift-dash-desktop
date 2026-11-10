import hashlib
import os
import pathlib
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

from dashsync import ffmpegtool

POSIX = os.name != "nt"


def fake(folder, name, version="7.1"):
    """A stand-in program that answers -version the way ffmpeg and ffprobe do."""
    p = os.path.join(folder, name)
    with open(p, "w") as f:
        f.write("#!/bin/sh\necho '%s version %s Copyright (c) the FFmpeg developers'\n" % (name, version))
    os.chmod(p, 0o755)
    return p


@unittest.skipUnless(POSIX, "the stand-ins are shell scripts")
class FfmpegToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"DASHSYNC_CONFIG": os.path.join(self.tmp, "config"),
                                                "PATH": os.path.join(self.tmp, "nowhere")})
        self.env.start()
        self.brew = mock.patch.object(ffmpegtool, "_HOMEBREW", ())
        self.brew.start()
        ffmpegtool.find(fresh=True)

    def tearDown(self):
        self.brew.stop()
        self.env.stop()
        ffmpegtool.find(fresh=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing(self):
        st = ffmpegtool.status()
        self.assertFalse(st["found"])
        self.assertIn("Download ffmpeg", st["hint"])
        with self.assertRaises(ffmpegtool.FfmpegMissing):
            ffmpegtool.require()

    def test_chosen_folder_needs_both(self):
        d = os.path.join(self.tmp, "mine")
        os.makedirs(d)
        fake(d, "ffmpeg")
        with self.assertRaises(ValueError):
            ffmpegtool.set_path(d)
        fake(d, "ffprobe")
        folder, v = ffmpegtool.set_path(os.path.join(d, "ffprobe"))      # either program picks its folder
        self.assertEqual((folder, v), (d, "7.1"))
        st = ffmpegtool.status()
        self.assertEqual((st["found"], st["source"], st["ffprobe"]), (True, "chosen in settings", os.path.join(d, "ffprobe")))
        ffmpegtool.forget_path()
        self.assertFalse(ffmpegtool.status()["found"])

    def test_on_path(self):
        d = os.path.join(self.tmp, "bin")
        os.makedirs(d)
        fake(d, "ffmpeg")
        fake(d, "ffprobe")
        with mock.patch.dict(os.environ, {"PATH": d}):
            self.assertEqual(ffmpegtool.find(fresh=True)["source"], "on your PATH")

    def _zip(self, name, version="8.0"):
        src = os.path.join(self.tmp, "src")
        os.makedirs(src, exist_ok=True)
        fake(src, name, version)
        z = os.path.join(self.tmp, name + ".zip")
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(os.path.join(src, name), name)          # zip keeps no executable bit: setup sets it
        with open(z, "rb") as f:
            return pathlib.Path(z).as_uri(), hashlib.sha256(f.read()).hexdigest()

    def test_setup_installs_both_and_checks_the_sums(self):
        items = []
        for n in ffmpegtool.NAMES:
            url, sha = self._zip(n)
            items.append((url, sha, {n: n}))
        with mock.patch.object(ffmpegtool, "downloads", return_value=items):
            folder, v = ffmpegtool.setup()
        self.assertEqual((folder, v), (ffmpegtool.own_dir(), "8.0"))
        st = ffmpegtool.status()
        self.assertEqual((st["found"], st["source"]), (True, "downloaded by this tool"))

    def test_setup_refuses_a_bad_sum(self):
        items = [(self._zip(n)[0], "0" * 64, {n: n}) for n in ffmpegtool.NAMES]
        with mock.patch.object(ffmpegtool, "downloads", return_value=items):
            with self.assertRaises(RuntimeError):
                ffmpegtool.setup()
        self.assertFalse(os.path.exists(ffmpegtool.own_dir()))
        self.assertFalse(ffmpegtool.status()["found"])


if __name__ == "__main__":
    unittest.main()
