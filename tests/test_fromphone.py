import datetime
import hashlib
import json
import os
import shutil
import struct
import tempfile
import unittest
from unittest import mock

from dashsync import fromphone, maps, paths, profile, vehicles, voice
from dashsync.transport import FolderTarget


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def read(path):
    with open(path, "rb") as f:
        return f.read()


def map_bytes(size):
    """A file that passes maps.check."""
    when = datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)
    head = maps.MAGIC + struct.pack(">iiqq", 100, 5, size, int(when.timestamp() * 1000))
    return head + b"\0" * (size - len(head))


def snapshot(root):
    """{path: digest} for every file under root."""
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root)] = hashlib.sha1(read(p)).hexdigest()
    return out


CATALOG = [{"name": "bakkie-land.map", "path": "africa/bakkie-land.map", "dir": False, "approx_bytes": 2000}]


class FromPhoneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"DASHSYNC_CONFIG": os.path.join(self.tmp, "config"),
                                                "DASHSYNC_CACHE": os.path.join(self.tmp, "cache")})
        self.env.start()
        self.catalog = mock.patch("dashsync.maps.catalog", return_value=CATALOG)
        self.catalog.start()
        self.card = os.path.join(self.tmp, "card")
        c = self.card + "/coldshift.dash/"
        write(c + "profile/profile.json", json.dumps({"version": 1, "title": "BAKKIE", "badges": []}).encode())
        write(c + "profile/car.png", b"car" * 10)
        write(c + "voice/sam/voice.json", json.dumps({"id": "sam", "name": "Sam", "lines": {"turn_left": "a.mp3"}}).encode())
        write(c + "voice/sam/a.mp3", b"a" * 40)
        write(c + "voice/loose/readme.txt", b"not a pack")
        write(c + "maps/bakkie-land.map", map_bytes(2000))
        write(c + "Music/Band/one.mp3", b"1" * 100)
        write(c + "Music/Band/two.mp3", b"2" * 200)
        write(c + "library/index.json", b"{}")
        self.t = FolderTarget(self.card)
        self.ws = vehicles.create("Bakkie", os.path.join(self.tmp, "bakkie"))["folder"]

    def tearDown(self):
        self.catalog.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_new_vehicle_gets_everything_and_the_phone_is_untouched(self):
        before = snapshot(self.card)
        r = fromphone.pull(self.t, self.ws)
        self.assertEqual(snapshot(self.card), before)
        self.assertEqual(read(self.ws + "/profile/car.png"), b"car" * 10)
        self.assertEqual(profile.load(self.ws)["title"], "BAKKIE")
        self.assertEqual([m["id"] for _, m in voice.packs(self.ws)], ["sam"])
        self.assertEqual(maps.cached("bakkie-land.map"), os.path.join(self.tmp, "cache", "bakkie-land.map"))
        self.assertEqual((r["map"]["region"], r["map"]["was"], r["map"]["found"]), ("africa/bakkie-land.map", None, True))
        self.assertEqual(maps.chosen(), "africa/bakkie-land.map")
        self.assertEqual(read(self.ws + "/coldshift.dash/Music/Band/two.mp3"), b"2" * 200)
        self.assertEqual(read(self.ws + "/coldshift.dash/library/index.json"), b"{}")
        self.assertEqual((r["music"]["songs"], r["music"]["bytes"]), (2, 300))
        self.assertEqual(fromphone.says(r), ["its look (BAKKIE)", "1 voice pack", "the map (bakkie-land)", "2 songs (0 MB)"])
        self.assertEqual(fromphone.moved(r), [])                  # nothing was here to replace
        self.assertEqual([f for f in os.listdir(self.ws) if f.endswith(".previous")], [])

    def test_a_second_pull_copies_nothing(self):
        fromphone.pull(self.t, self.ws)
        r = fromphone.pull(self.t, self.ws)
        self.assertEqual((fromphone.says(r), fromphone.moved(r)), ([], []))

    def test_dry_run_says_what_the_phone_has_and_changes_nothing(self):
        write(self.ws + "/coldshift.dash/Music/Other/mine.mp3", b"m")
        before = snapshot(self.ws)
        r = fromphone.pull(self.t, self.ws, dry_run=True)
        self.assertEqual(snapshot(self.ws), before)
        self.assertIsNone(maps.cached("bakkie-land.map"))
        self.assertIsNone(maps.chosen())
        self.assertEqual(fromphone.says(r), ["its look", "1 voice pack", "the map (bakkie-land)", "2 songs (0 MB)"])
        self.assertEqual(r["music"]["removed"], 1)

    def test_the_phones_look_replaces_this_one_and_the_old_is_moved_aside(self):
        profile.init(self.ws)
        write(self.ws + "/profile/badge.png", b"mine")
        old = snapshot(self.ws + "/profile")
        r = fromphone.look(self.t, self.ws)
        self.assertEqual(snapshot(self.ws + "/profile"), snapshot(self.card + "/coldshift.dash/profile"))
        self.assertIn("badge.png", snapshot(self.ws + "/profile.previous"))
        self.assertEqual(snapshot(self.ws + "/profile.previous")["profile.json"], old["profile.json"])
        self.assertTrue(r["replaced"] and r["removed"])

    def test_a_phone_without_a_look_gives_the_vehicle_the_built_in_one(self):
        shutil.rmtree(self.card + "/coldshift.dash/profile")
        write(self.ws + "/profile/profile.json", json.dumps({"version": 1, "title": "MINE"}).encode())
        r = fromphone.look(self.t, self.ws)
        self.assertFalse(r["present"])
        self.assertEqual(json.loads(read(self.ws + "/profile.previous/profile.json"))["title"], "MINE")
        self.assertNotEqual(profile.load(self.ws).get("title"), "MINE")       # the built-in look again
        self.assertEqual(fromphone.says({"look": r}), ["the built-in look (the phone has no look of its own)"])

    def test_voice_packs_only_here_are_moved_aside(self):
        write(self.ws + "/voice/mine/voice.json", json.dumps({"id": "mine", "name": "Mine", "lines": {}}).encode())
        r = fromphone.voices(self.t, self.ws)
        self.assertEqual(r["packs"], ["sam"])
        self.assertEqual([m["id"] for _, m in voice.packs(self.ws)], ["sam"])
        self.assertTrue(os.path.exists(self.ws + "/voice.previous/mine/voice.json"))

    def test_a_pack_both_have_takes_the_phones_files(self):
        write(self.ws + "/voice/sam/voice.json", json.dumps({"id": "sam", "name": "Sam", "lines": {"turn_left": "b.mp3"}}).encode())
        write(self.ws + "/voice/sam/b.mp3", b"b" * 10)
        fromphone.voices(self.t, self.ws)
        self.assertEqual(sorted(os.listdir(self.ws + "/voice/sam")), ["a.mp3", "voice.json"])
        self.assertEqual(read(self.ws + "/voice.previous/sam/b.mp3"), b"b" * 10)

    def test_the_phones_map_becomes_the_vehicles_region(self):
        cfg = paths.load_config()
        cfg["map_region"] = "europe/elsewhere.map"
        paths.save_config(cfg)
        r = fromphone.the_map(self.t)
        self.assertEqual((r["region"], r["was"]), ("africa/bakkie-land.map", "europe/elsewhere.map"))
        self.assertEqual(maps.chosen(), "africa/bakkie-land.map")

    def test_offline_the_map_is_copied_and_the_region_left_to_choose(self):
        with mock.patch("dashsync.maps.catalog", side_effect=OSError("offline")):
            r = fromphone.the_map(self.t)
        self.assertEqual((r["copied"], r["region"], r["found"]), (True, None, None))
        self.assertTrue(maps.cached("bakkie-land.map"))

    def test_a_map_the_server_does_not_have_leaves_the_region(self):
        with mock.patch("dashsync.maps.catalog", return_value=[]):
            r = fromphone.the_map(self.t)
        self.assertEqual((r["region"], r["found"]), (None, False))

    def test_a_map_already_in_the_cache_is_not_copied_again(self):
        write(os.path.join(self.tmp, "cache", "bakkie-land.map"), map_bytes(2000))
        self.assertFalse(fromphone.the_map(self.t)["copied"])

    def test_a_cached_map_whose_region_is_not_chosen_is_still_news(self):
        write(os.path.join(self.tmp, "cache", "bakkie-land.map"), map_bytes(2000))
        r = fromphone.pull(self.t, self.ws, only=["map"], dry_run=True)
        self.assertEqual(fromphone.says(r), ["the map (bakkie-land)"])

    def test_a_broken_map_on_the_phone_never_reaches_the_cache(self):
        write(self.card + "/coldshift.dash/maps/bakkie-land.map", b"not a map" * 100)
        with self.assertRaises(ValueError):
            fromphone.the_map(self.t)
        self.assertEqual(os.listdir(os.path.join(self.tmp, "cache")), [])

    def test_the_phones_songs_replace_these_and_songs_only_here_are_moved_aside(self):
        write(self.ws + "/coldshift.dash/Music/Band/one.mp3", b"mine")
        write(self.ws + "/coldshift.dash/Music/Other/only-here.mp3", b"o")
        r = fromphone.music(self.t, self.ws)
        self.assertEqual((r["songs"], r["replaced"], r["removed"]), (2, 1, 1))
        self.assertEqual(read(self.ws + "/coldshift.dash/Music/Band/one.mp3"), b"1" * 100)
        self.assertEqual(read(self.ws + "/coldshift.dash/Music.previous/Band/one.mp3"), b"mine")
        self.assertEqual(read(self.ws + "/coldshift.dash/Music.previous/Other/only-here.mp3"), b"o")
        self.assertFalse(os.path.exists(self.ws + "/coldshift.dash/Music/Other"))     # its empty folder went
        self.assertEqual(fromphone.moved({"music": r}), ["Music.previous"])

    def test_a_song_kept_here_under_its_emoji_name_is_the_phones_song(self):
        write(self.card + "/coldshift.dash/Music/Band/girl U+1F338.mp3", b"g" * 50)
        write(self.ws + "/coldshift.dash/Music/Band/girl 🌸.mp3", b"g" * 50)
        r = fromphone.music(self.t, self.ws)
        self.assertEqual((r["songs"], r["removed"]), (2, 0))
        self.assertTrue(os.path.exists(self.ws + "/coldshift.dash/Music/Band/girl 🌸.mp3"))
        self.assertFalse(os.path.exists(self.ws + "/coldshift.dash/Music/Band/girl U+1F338.mp3"))

    def test_a_music_filter_takes_nothing_away(self):
        write(self.ws + "/coldshift.dash/Music/Other/only-here.mp3", b"o")
        r = fromphone.music(self.t, self.ws, music_match="two")
        self.assertEqual((r["songs"], r["removed"]), (1, 0))
        self.assertTrue(os.path.exists(self.ws + "/coldshift.dash/Music/Other/only-here.mp3"))

    def test_not_enough_space_moves_nothing(self):
        write(self.ws + "/coldshift.dash/Music/Band/one.mp3", b"mine")
        with mock.patch("dashsync.fromphone.shutil.disk_usage", return_value=mock.Mock(free=1000)):
            with self.assertRaises(RuntimeError):
                fromphone.music(self.t, self.ws)
        self.assertEqual(read(self.ws + "/coldshift.dash/Music/Band/one.mp3"), b"mine")


if __name__ == "__main__":
    unittest.main()
