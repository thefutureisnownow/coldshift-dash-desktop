import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

from dashsync import adbtool, paths

FAKE_OK = """#!/bin/sh
case "$1" in
  version) echo "Android Debug Bridge version 1.0.41"; echo "Version 99.0.0-fake";;
  devices) echo "List of devices attached"
           echo "AAA111                 device usb:1-1 product:G7-L01 model:G7_L01 device:hwG7-L01 transport_id:1"
           echo "BBB222                 unauthorized usb:1-2 transport_id:2"
           echo "192.168.0.5:5555       device product:G7-L01 model:G7_L01 device:hwG7-L01 transport_id:3";;
esac
"""
FAKE_BAD = "#!/bin/sh\nexit 1\n"


def make_exe(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


@unittest.skipIf(os.name == "nt", "uses shell scripts as fake adb")
class AdbToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"DASHSYNC_CONFIG": self.tmp + "/config", "HOME": self.tmp + "/home",
                                                "PATH": "/usr/bin:/bin"}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_not_found_gives_instructions(self):
        st = adbtool.status()
        self.assertFalse(st["found"])
        self.assertIn("Download adb", st["hint"])
        with self.assertRaises(adbtool.AdbMissing):
            adbtool.require()

    def test_finds_adb_on_path(self):
        make_exe(self.tmp + "/bin/adb", FAKE_OK)
        os.environ["PATH"] += ":" + self.tmp + "/bin"
        st = adbtool.status()
        self.assertTrue(st["found"])
        self.assertEqual((st["source"], st["version"]), ("on your PATH", "99.0.0-fake"))

    def test_broken_adb_is_skipped_for_a_working_one(self):
        make_exe(self.tmp + "/bad/adb", FAKE_BAD)
        good = make_exe(self.tmp + "/good/adb", FAKE_OK)
        os.environ["ADB"] = self.tmp + "/bad/adb"
        os.environ["PATH"] += ":" + self.tmp + "/good"
        self.assertEqual(adbtool.find_adb()[0], good)

    def test_chosen_path_beats_path_and_survives_restart(self):
        make_exe(self.tmp + "/bin/adb", FAKE_OK)
        os.environ["PATH"] += ":" + self.tmp + "/bin"
        mine = make_exe(self.tmp + "/mine/adb", FAKE_OK)
        adbtool.set_path(self.tmp + "/mine")           # a folder is accepted
        self.assertEqual(adbtool.find_adb()[:2], (mine, "chosen in settings"))
        adbtool.forget_path()
        self.assertEqual(adbtool.find_adb()[1], "on your PATH")

    def test_set_path_rejects_things_that_are_not_adb(self):
        open(self.tmp + "/notadb", "w").write("hello")
        with self.assertRaises(ValueError):
            adbtool.set_path(self.tmp + "/notadb")
        make_exe(self.tmp + "/bad/adb", FAKE_BAD)
        with self.assertRaises(ValueError):
            adbtool.set_path(self.tmp + "/bad/adb")

    def test_device_list_parses_states_and_wifi(self):
        adb = make_exe(self.tmp + "/bin/adb", FAKE_OK)
        devs = {d["serial"]: d for d in adbtool.list_devices(adb)}
        self.assertEqual(devs["AAA111"]["model"], "G7 L01")
        self.assertEqual(devs["BBB222"]["state"], "unauthorized")
        self.assertTrue(devs["192.168.0.5:5555"]["wifi"])
        self.assertFalse(devs["AAA111"]["wifi"])

    def test_setup_needs_the_licence_accepted(self):
        with self.assertRaises(PermissionError):
            adbtool.setup(False)


if __name__ == "__main__":
    unittest.main()
