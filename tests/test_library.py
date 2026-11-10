import os
import shutil
import tempfile
import unittest
from unittest import mock

from dashsync import library


class CoverTest(unittest.TestCase):
    def test_failed_cover_conversion_leaves_no_file_and_no_key(self):
        tmp = tempfile.mkdtemp()
        try:
            music, art = os.path.join(tmp, "m"), os.path.join(tmp, "art")
            os.makedirs(music)
            os.makedirs(art)
            with open(os.path.join(music, "a.mp3"), "wb") as f:
                f.write(b"\0" * 100)
            with mock.patch.object(library, "_picture", return_value=b"not an image"):
                e = library.read_track(music, "a.mp3", art)
            self.assertEqual(e["k"], "")
            self.assertEqual(os.listdir(art), [])
        finally:
            shutil.rmtree(tmp)

    def test_unsafe_names_flags_only_characters_outside_the_basic_plane(self):
        names = ["a/Café – 日本語.mp3", "a/zero\u200bwidth.mp3", "a/note 🎶.mp3"]
        self.assertEqual(library.unsafe_names(names), ["a/note 🎶.mp3"])


    def test_card_name_drops_what_the_phone_garbles(self):
        cases = {"a/Samurai Girl 🎶🌸.mp3": "a/Samurai Girl U+1F3B6 U+1F338.mp3",
                 "a/【Metal】🔥 The Collision! ⚡.mp3": "a/【Metal】 U+1F525 The Collision! ⚡.mp3",   # ⚡ is in the BMP
                 "a/Epic! ⚔️🔥.mp3": "a/Epic! ⚔️ U+1F525.mp3",     # keeps ⚔ and its variation selector
                 "a/👍🏽 ok.mp3": "a/U+1F44D U+1F3FD ok.mp3",       # skin tone modifier
                 "a/👨‍👩 fam.mp3": "a/U+1F468 U+1F469 fam.mp3",     # the joiner between them goes
                 "a/🔥.mp3": "a/U+1F525.mp3",
                 "🎶 Mix/x.mp3": "U+1F3B6 Mix/x.mp3",
                 "a/Café – 日本語.mp3": "a/Café – 日本語.mp3"}
        for rel, want in cases.items():
            self.assertEqual(library.card_name(rel), want, rel)

    def test_card_names_resolve_clashes_case_insensitively(self):
        names = library.card_names(["a/x 🎶.mp3", "a/X U+1F3B6.mp3", "a/y.mp3"])
        self.assertEqual(names, {"a/X U+1F3B6.mp3": "a/X U+1F3B6.mp3", "a/x 🎶.mp3": "a/x U+1F3B6 (2).mp3",
                                 "a/y.mp3": "a/y.mp3"})

    def test_index_uses_card_names(self):
        tmp = tempfile.mkdtemp()
        try:
            music, lib = os.path.join(tmp, "m"), os.path.join(tmp, "lib")
            os.makedirs(os.path.join(music, "a"))
            with open(os.path.join(music, "a", "song 🎶.mp3"), "wb") as f:
                f.write(b"\0" * 100)
            r = library.build_index(music, lib)
            self.assertEqual(r["renamed"], [("a/song 🎶.mp3", "a/song U+1F3B6.mp3")])
            import json
            with open(os.path.join(lib, "index.json"), encoding="utf-8") as f:
                self.assertEqual([t["p"] for t in json.load(f)["tracks"]], ["a/song U+1F3B6.mp3"])
            self.assertEqual(library.build_index(music, lib)["reused"], 1)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
