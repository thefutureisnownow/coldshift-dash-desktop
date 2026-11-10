import json
import os
import shutil
import tempfile
import unittest

from dashsync import library, mirror
from dashsync.transport import FolderTarget


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def read(path):
    with open(path, "rb") as f:
        return f.read()


class Card(FolderTarget):
    """A card in a folder that also records what the app was told."""
    kind = "adb"

    def __init__(self, root):
        super().__init__(root)
        self.told = []

    def notify_synced(self, what):
        self.told.append(what)
        return "reloaded " + ",".join(what)


class PushTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, "ws")
        self.card_root = os.path.join(self.tmp, "card")
        self.music = self.ws + "/coldshift.dash/Music"
        write(self.music + "/Nightwish/one.mp3", b"1" * 100)
        write(self.music + "/Nightwish/two.mp3", b"2" * 200)
        write(self.music + "/Pet Shop Boys/three.mp3", b"3" * 300)
        write(self.music + "/Pet Shop Boys/.DS_Store", b"x")
        os.makedirs(self.card_root)
        self.card = Card(self.card_root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def on_card(self, rel):
        return os.path.join(self.card_root, "coldshift.dash", *rel.split("/"))

    def test_first_push_copies_music_then_index_and_tells_the_app(self):
        r = mirror.push_music(self.card, self.ws)
        self.assertEqual(r["copied"], 3)
        self.assertEqual(read(self.on_card("Music/Pet Shop Boys/three.mp3")), b"3" * 300)
        self.assertFalse(os.path.exists(self.on_card("Music/Pet Shop Boys/.DS_Store")))
        index = json.loads(read(self.on_card("library/index.json")))
        self.assertEqual(sorted(t["p"] for t in index["tracks"]),
                         ["Nightwish/one.mp3", "Nightwish/two.mp3", "Pet Shop Boys/three.mp3"])
        self.assertEqual(self.card.told, [["music"]])
        self.assertEqual(r["app"], "reloaded music")

    def test_second_push_copies_nothing_and_keeps_the_index_stamp(self):
        mirror.push_music(self.card, self.ws)
        stamp = json.loads(read(self.on_card("library/index.json")))["generated"]
        r = mirror.push_music(self.card, self.ws)
        self.assertEqual((r["copied"], r["music"]["same"]), (0, 3))
        self.assertFalse(r["index"]["changed"])
        self.assertEqual(json.loads(read(self.on_card("library/index.json")))["generated"], stamp)

    def test_dry_run_changes_nothing(self):
        r = mirror.push_music(self.card, self.ws, dry_run=True)
        self.assertEqual(len(r["music"]["copy"]), 3)
        self.assertFalse(os.path.exists(self.on_card("Music")))
        self.assertEqual(self.card.told, [])

    def test_conflict_is_kept_unless_overwrite(self):
        write(self.on_card("Music/Nightwish/one.mp3"), b"card's own copy")
        r = mirror.push_music(self.card, self.ws)
        self.assertEqual(r["music"]["conflicts"], [("Nightwish/one.mp3", 15, 100)])
        self.assertEqual(read(self.on_card("Music/Nightwish/one.mp3")), b"card's own copy")
        mirror.push_music(self.card, self.ws, overwrite=True)
        self.assertEqual(read(self.on_card("Music/Nightwish/one.mp3")), b"1" * 100)

    def test_extra_music_kept_unless_asked_and_empty_folders_go(self):
        write(self.on_card("Music/Old Band/Album/gone.mp3"), b"g" * 10)
        r = mirror.push_music(self.card, self.ws)
        self.assertEqual(r["music"]["extra"], [("Old Band/Album/gone.mp3", 10)])
        self.assertTrue(os.path.exists(self.on_card("Music/Old Band/Album/gone.mp3")))
        r = mirror.push_music(self.card, self.ws, delete_extra=True)
        self.assertEqual(r["deleted"], 1)
        self.assertFalse(os.path.exists(self.on_card("Music/Old Band")))
        self.assertTrue(os.path.isdir(self.on_card("Music/Nightwish")))

    def test_unused_and_empty_covers_are_removed_from_the_card(self):
        write(self.on_card("library/art/0000000000000000.jpg"), b"")
        r = mirror.push_music(self.card, self.ws)
        self.assertEqual(r["stale_covers"], 1)
        self.assertFalse(os.path.exists(self.on_card("library/art/0000000000000000.jpg")))

    def test_emoji_names_go_to_the_card_without_them(self):
        write(self.music + "/Samurai/girl 🎶🌸.mp3", b"s" * 50)
        r = mirror.push_music(self.card, self.ws)
        self.assertEqual(r["music"]["renamed"], 1)
        self.assertEqual(read(self.on_card("Music/Samurai/girl U+1F3B6 U+1F338.mp3")), b"s" * 50)
        self.assertFalse(os.path.exists(self.on_card("Music/Samurai/girl 🎶🌸.mp3")))
        index = json.loads(read(self.on_card("library/index.json")))
        self.assertIn("Samurai/girl U+1F3B6 U+1F338.mp3", [t["p"] for t in index["tracks"]])
        r = mirror.push_music(self.card, self.ws)
        self.assertEqual((r["copied"], r["music"]["extra"]), (0, []))

    def test_song_already_on_the_card_under_its_emoji_name_is_renamed_not_copied(self):
        write(self.music + "/Samurai 🎶/girl 🌸.mp3", b"s" * 50)
        write(self.on_card("Music/Samurai 🎶/girl 🌸.mp3"), b"s" * 50)
        r = mirror.push_music(self.card, self.ws)
        self.assertEqual(r["moved"], 1)
        self.assertEqual([c[1] for c in r["music"]["copy"] if "girl" in c[1]], [])
        self.assertEqual(read(self.on_card("Music/Samurai U+1F3B6/girl U+1F338.mp3")), b"s" * 50)
        self.assertFalse(os.path.exists(self.on_card("Music/Samurai 🎶")))     # its folder went with it

    def test_pull_does_not_bring_renamed_songs_back_as_copies(self):
        write(self.music + "/Samurai/girl 🎶.mp3", b"s" * 50)
        mirror.push_music(self.card, self.ws)
        r = mirror.pull_all(self.card, [self.card], self.ws, only=["music"], log=lambda m: None)
        self.assertEqual(r["music"]["pulled"], 0)
        self.assertFalse(os.path.exists(self.music + "/Samurai/girl U+1F3B6.mp3"))

    def test_no_music_folder(self):
        shutil.rmtree(self.music)
        with self.assertRaises(SystemExit):
            mirror.push_music(self.card, self.ws)


class IndexStampTest(unittest.TestCase):
    def test_unchanged_library_keeps_its_file(self):
        tmp = tempfile.mkdtemp()
        try:
            music, lib = os.path.join(tmp, "m"), os.path.join(tmp, "lib")
            write(os.path.join(music, "a.mp3"), b"\0" * 100)
            self.assertTrue(library.build_index(music, lib)["changed"])
            first = read(os.path.join(lib, "index.json"))
            self.assertFalse(library.build_index(music, lib)["changed"])
            self.assertEqual(read(os.path.join(lib, "index.json")), first)
            write(os.path.join(music, "b.mp3"), b"\0" * 50)
            self.assertTrue(library.build_index(music, lib)["changed"])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
