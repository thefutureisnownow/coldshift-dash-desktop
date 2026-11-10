import subprocess
import unittest
from unittest import mock

from dashsync import transport


class LsTest(unittest.TestCase):
    def parse(self, line):
        m = transport._LS.match(line)
        return m and m.groups()

    def test_toolbox(self):
        # Android 4.4
        self.assertEqual(self.parse("-rw-rw-r-- root sdcard_r 996370 2026-11-04 10:27 interior_1.jpg"),
                         ("-", "996370", "2026-11-04 10:27", "interior_1.jpg"))
        self.assertEqual(self.parse("drwxrwx--- u0_a95 sdcard_r 2026-11-01 17:11 marks"),
                         ("d", None, "2026-11-01 17:11", "marks"))

    def test_toybox(self):
        # Android 6 and later: a link count after the mode
        self.assertEqual(self.parse("-rwxrwx--- 1 root everybody 3548444 2026-11-04 10:43 interior 2.jpg"),
                         ("-", "3548444", "2026-11-04 10:43", "interior 2.jpg"))
        self.assertEqual(self.parse("drwxrwx--- 2 root everybody 3488 2026-11-04 10:43 Interior"),
                         ("d", "3488", "2026-11-04 10:43", "Interior"))


A22_MOUNTS = ("/dev/block/vold/public:179,129 /mnt/media_rw/89AC-1704 sdfat rw 0 0\n"
              "/dev/fuse /storage/89AC-1704 fuse rw 0 0\n")
GONE = "adb: device 'X' not found\n"


class PhoneTest(unittest.TestCase):
    """What the phone answers, and what it means when it does not."""

    def target(self, code=0, out="", err="", card="/storage/CARD"):
        self.addCleanup(mock.patch.stopall)
        mock.patch("dashsync.transport.adbtool.require", return_value="adb").start()
        run = mock.patch("dashsync.transport.subprocess.run").start()
        run.return_value = subprocess.CompletedProcess([], code, out, err)
        return transport.AdbTarget("X", "adb", card)

    def test_finds_the_card(self):
        self.assertEqual(self.target(out=A22_MOUNTS, card=None).card, "/storage/89AC-1704")

    def test_no_card_means_internal_storage(self):
        self.assertEqual(self.target(out="/dev/fuse /storage/emulated fuse rw 0 0\n", card=None).card, "/storage/emulated/0")

    def test_lost_phone_is_not_a_phone_without_a_card(self):
        with self.assertRaises(SystemExit) as e:
            self.target(code=1, err=GONE, card=None)
        self.assertIn("stopped answering", str(e.exception.code))
        self.assertIn("not found", str(e.exception.code))

    def test_lost_phone_is_not_a_missing_folder(self):
        with self.assertRaises(SystemExit):
            self.target(code=1, err=GONE).exists("Dashcam")
        with self.assertRaises(SystemExit):
            self.target(code=1, err="error: closed\n").listdir("Dashcam")

    def test_a_missing_folder_is_still_missing(self):
        self.assertFalse(self.target(code=1).exists("Dashcam"))
        self.assertEqual(self.target(code=1, err="ls: /storage/CARD/Dashcam: No such file or directory\n").listdir("Dashcam"), [])

    def test_losing_the_phone_after_a_copy_does_not_fail_it(self):
        self.assertIsNone(self.target(code=1, err=GONE).notify_synced(["maps"]))


if __name__ == "__main__":
    unittest.main()
