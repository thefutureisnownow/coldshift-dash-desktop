import os
import shutil
import tempfile
import unittest
from unittest import mock

from dashsync import mirror
from dashsync.transport import FolderTarget


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class MirrorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.card = os.path.join(self.tmp, "card")
        self.ws = os.path.join(self.tmp, "ws")
        write(self.card + "/coldshift.dash/Music/Pet Shop Boys/one.mp3", b"1" * 100)
        write(self.card + "/coldshift.dash/Music/Pet Shop Boys/two.mp3", b"2" * 200)
        write(self.card + "/coldshift.dash/Music/Nightwish/3 - song 🎶.mp3", b"3" * 300)
        write(self.card + "/coldshift.dash/Music/Nightwish/.hidden", b"h")
        write(self.card + "/coldshift.dash/Music/Nightwish/half.mp3.part", b"p")
        write(self.card + "/coldshift.dash/maps/a.map", b"m" * 50)
        write(self.card + "/coldshift.dash/library/index.json", b"{}")
        self.t = FolderTarget(self.card)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def pull(self, **kw):
        return mirror.pull_all(self.t, [self.t], self.ws, log=lambda m: None, **kw)

    def test_pulls_everything_and_skips_dotfiles_and_partials(self):
        r = self.pull(only=["music", "maps", "library"])
        self.assertEqual(r["music"]["pulled"], 3)
        self.assertTrue(os.path.exists(self.ws + "/coldshift.dash/Music/Nightwish/3 - song 🎶.mp3"))
        self.assertFalse(os.path.exists(self.ws + "/coldshift.dash/Music/Nightwish/.hidden"))
        self.assertFalse(os.path.exists(self.ws + "/coldshift.dash/Music/Nightwish/half.mp3.part"))
        self.assertEqual(r["maps"]["pulled"], 1)

    def test_second_pull_copies_nothing(self):
        self.pull(only=["music"])
        r = self.pull(only=["music"])
        self.assertEqual((r["music"]["pulled"], r["music"]["had"]), (0, 3))

    def test_adopts_files_already_on_the_computer(self):
        write(self.ws + "/coldshift.dash/Music/Pet Shop Boys/one.mp3", b"1" * 100)
        r = self.pull(only=["music"])
        self.assertEqual((r["music"]["pulled"], r["music"]["had"]), (2, 1))

    def test_different_local_file_is_kept_until_overwrite(self):
        write(self.ws + "/coldshift.dash/Music/Pet Shop Boys/one.mp3", b"mine")
        r = self.pull(only=["music"])
        self.assertEqual(len(r["music"]["conflicts"]), 1)
        with open(self.ws + "/coldshift.dash/Music/Pet Shop Boys/one.mp3", "rb") as f:
            self.assertEqual(f.read(), b"mine")
        self.pull(only=["music"], overwrite=True)
        self.assertEqual(os.path.getsize(self.ws + "/coldshift.dash/Music/Pet Shop Boys/one.mp3"), 100)

    def test_music_filters(self):
        r = self.pull(only=["music"], music_path="Pet Shop Boys")
        self.assertEqual(r["music"]["pulled"], 2)
        r = self.pull(only=["music"], music_match="song")
        self.assertEqual(r["music"]["pulled"], 1)

    def test_dry_run_copies_nothing(self):
        r = self.pull(only=["music"], dry_run=True)
        self.assertEqual((r["music"]["would_pull"], r["music"]["would_bytes"]), (3, 600))
        self.assertFalse(os.path.exists(self.ws + "/coldshift.dash/Music"))

    def test_refuses_when_the_disk_is_too_small(self):
        with mock.patch("dashsync.mirror.shutil.disk_usage", return_value=mock.Mock(free=1000)):
            with self.assertRaises(RuntimeError):
                self.pull(only=["music"])
        self.assertFalse(os.path.exists(self.ws + "/coldshift.dash/Music/Pet Shop Boys/one.mp3"))

    def test_plain_music_folder_is_used_when_there_is_no_coldshift_folder(self):
        shutil.move(self.card + "/coldshift.dash/Music", self.card + "/Music")
        r = self.pull(only=["music"])
        self.assertEqual(r["music"]["pulled"], 3)
        self.assertTrue(os.path.exists(self.ws + "/coldshift.dash/Music/Nightwish/3 - song 🎶.mp3"))

    def test_workspace_layout_matches_the_card(self):
        self.pull(only=["music", "maps", "library"])
        for rel in ("coldshift.dash/Music/Pet Shop Boys/one.mp3", "coldshift.dash/maps/a.map",
                    "coldshift.dash/library/index.json"):
            self.assertTrue(os.path.exists(os.path.join(self.ws, *rel.split("/"))), rel)

    def test_missing_folders_are_reported_not_fatal(self):
        r = self.pull(only=["profile"])
        self.assertFalse(r["profile"]["present"])

    def test_unknown_section(self):
        with self.assertRaises(ValueError):
            self.pull(only=["nonsense"])

    def test_size_mismatch_after_copy_leaves_no_file(self):
        real = self.t.pull

        def bad(rel, local):
            real(rel, local)
            with open(local, "ab") as f:
                f.write(b"extra")
        self.t.pull = bad
        with self.assertRaises(RuntimeError):
            self.pull(only=["music"])
        left = [n for _, _, fs in os.walk(self.ws) for n in fs]
        self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()
