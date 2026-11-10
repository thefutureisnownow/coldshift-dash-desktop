import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from dashsync import voice
from dashsync.transport import FolderTarget

# the car app's source, from a coldshift-dash checkout beside this one (its test is skipped without it)
APP = os.environ.get("COLDSHIFT_DASH_SRC") or os.path.join(os.path.dirname(__file__), "..", "..", "coldshift-dash",
                                                             "android", "car", "src", "racing", "coldshift", "dash")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def tone(path, seconds=0.5):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=%f" % seconds,
                    "-c:a", "libmp3lame", path], check=True)


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg to make test recordings")
class VoiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, "ws")
        self.rec = os.path.join(self.tmp, "left.mp3")
        tone(self.rec)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_pack_is_built_a_line_at_a_time(self):
        folder = voice.create(self.ws, "Sam's voice")
        self.assertEqual(os.path.basename(folder), "sam-s-voice")
        self.assertEqual(voice.recorded(voice.read_pack(folder)), (0, len(voice.LINES)))
        self.assertAlmostEqual(voice.set_line(folder, "turn_left", self.rec), 0.5, delta=0.1)
        wav = os.path.join(self.tmp, "left.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", self.rec, wav], check=True)
        voice.set_line(folder, "turn_left", wav)                       # replaced, the old file removed
        self.assertEqual(sorted(os.listdir(folder)), ["turn_left.wav", "voice.json"])
        voice.rename(folder, "Sam")
        self.assertEqual(voice.read_pack(folder)["name"], "Sam")
        voice.remove_line(folder, "turn_left")
        self.assertEqual(sorted(os.listdir(folder)), ["voice.json"])

    def test_recordings_are_checked(self):
        folder = voice.create(self.ws, "Sam")
        junk = os.path.join(self.tmp, "notes.mp3")
        with open(junk, "w") as f:
            f.write("not audio")
        long = os.path.join(self.tmp, "long.mp3")
        tone(long, voice.MAX_SECONDS + 2)
        for bad in (junk, long, os.path.join(self.tmp, "x.flac")):
            if not os.path.exists(bad):
                open(bad, "w").close()
            with self.assertRaises(ValueError):
                voice.set_line(folder, "turn_left", bad)
        with self.assertRaises(ValueError):
            voice.set_line(folder, "sing_a_song", self.rec)

    def test_new_packs_never_take_the_builtin_id_and_can_start_from_it(self):
        if not voice.builtin_dir():
            self.skipTest("not running from the repository")
        folder = voice.create(self.ws, "Angie", voice.builtin_dir())
        self.assertEqual(os.path.basename(folder), "angie-2")
        meta = voice.read_pack(folder)
        self.assertEqual((meta["id"], voice.recorded(meta)), ("angie-2", (len(voice.LINES), len(voice.LINES))))

    def test_export_install_and_sync_mirror_the_card(self):
        folder = voice.create(self.ws, "Bob")
        voice.set_line(folder, "turn_left", self.rec)
        shared = voice.export(folder, os.path.join(self.tmp, "bob.zip"))
        voice.delete(folder)
        self.assertEqual(voice.packs(self.ws), [])
        self.assertEqual(voice.install(shared, self.ws)["name"], "Bob")
        voice.create(self.ws, "Empty")

        os.makedirs(os.path.join(self.tmp, "card", "coldshift.dash", "voice", "old"))
        card = FolderTarget(os.path.join(self.tmp, "card"))
        r = voice.sync(card, self.ws)
        self.assertEqual((r["copied"], r["removed"]), (3, 1))         # Bob's line and voice.json, Empty's voice.json
        self.assertEqual(sorted(e.name for e in card.listdir(voice.VOICE_DIR)), ["bob", "empty"])
        self.assertEqual(voice.sync(card, self.ws)["copied"], 0)
        voice.remove_line(os.path.join(voice.packs_dir(self.ws), "bob"), "turn_left")
        voice.sync(card, self.ws)
        self.assertEqual(sorted(e.name for e in card.listdir(voice.VOICE_DIR + "/bob")), ["voice.json"])

    def test_broken_packs_are_refused(self):
        bad = os.path.join(self.tmp, "bad")
        os.makedirs(bad)
        with open(os.path.join(bad, "voice.json"), "w") as f:
            json.dump({"id": "bad", "name": "Bad", "lines": {"turn_left": "turn_left.mp3"}}, f)
        with self.assertRaises(ValueError):
            voice.install(bad, self.ws)                                    # the clip is missing
        evil = os.path.join(self.tmp, "evil.zip")
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("../voice.json", "{}")
        with self.assertRaises(ValueError):
            voice.install(evil, self.ws)

    @unittest.skipUnless(os.path.isdir(APP), "needs the car app's source (coldshift-dash beside this repo)")
    def test_every_line_the_app_asks_for_exists(self):
        src = read(os.path.join(APP, "Prompter.java")) + read(os.path.join(APP, "MapsPage.java"))
        asked = set(re.findall(r'"((?:turn|keep|exit|in|gps|no|off)_[a-z0-9_]+|u_turn|straight|then|destination|arrived|'
                               r'roundabout)"', src))
        asked |= {"roundabout_%d" % i for i in range(1, 9)} | {"follow_%dkm" % k for k in (5, 10, 20, 50)}
        # the warnings: Cues.warn(…, "line") and Cues.notice(…, "line") in the dashcam and the main view
        for name in ("Dashcam.java", "UI.java"):
            path = os.path.join(APP, name)
            if os.path.exists(path):
                asked |= set(re.findall(r'Cues\.(?:warn|notice)\([^,]+, "([a-z_]+)"\)', read(path)))
        self.assertEqual(sorted(asked - set(voice.LINES)), [])
        grouped = [k for _, _, keys in voice.GROUPS for k in keys]
        self.assertEqual(sorted(grouped), sorted(voice.LINES))             # every line is shown once for recording


if __name__ == "__main__":
    unittest.main()
