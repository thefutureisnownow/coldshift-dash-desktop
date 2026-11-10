import json
import os
import shutil
import tempfile
import unittest

from dashsync import convoy, paths
from dashsync.transport import FolderTarget


class ConvoyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["DASHSYNC_CONFIG"] = os.path.join(self.tmp, "config")
        self.v = os.path.join(self.tmp, "vehicle")
        os.makedirs(self.v)
        with open(os.path.join(self.v, paths.VEHICLE_FILE), "w") as f:
            json.dump({"version": 1, "id": "raspberry", "name": "Peppermint Crisp"}, f)

    def tearDown(self):
        os.environ.pop("DASHSYNC_CONFIG", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_server_address(self):
        self.assertEqual(convoy.server(), "")                # no default host
        self.assertEqual(convoy.set_server(" http://192.168.0.10:8080/ "), "http://192.168.0.10:8080")
        self.assertEqual(convoy.server(), "http://192.168.0.10:8080")
        with self.assertRaises(ValueError):
            convoy.set_server("192.168.0.10:8080")
        with self.assertRaises(ValueError):
            convoy.set_server("https://convoy.example.com/path")

    def test_links(self):
        base = "https://convoy.example.com"
        token = "xwiJShdCsjWUvw38olGcPg9C"
        self.assertEqual(convoy.link(base, token), base + "/c/" + token)
        self.assertEqual(convoy.read_link(" " + base + "/c/" + token + "/"), (base, token))
        with self.assertRaises(ValueError):
            convoy.read_link("ABC123")

    def test_to_card(self):
        card = os.path.join(self.tmp, "card")
        os.makedirs(card)
        convoy.to_card(FolderTarget(card), self.v, "http://h:8080", {"token": "t" * 24, "name": "Sunday run",
                                                                    "password": "pw"})
        with open(os.path.join(card, *convoy.FILE.split("/"))) as f:
            got = json.load(f)
        self.assertTrue(got.pop("sent").isdigit())
        self.assertEqual(got, {"server": "http://h:8080", "name": "Peppermint Crisp",
                               "join": {"token": "t" * 24, "name": "Sunday run", "password": "pw"}})
        convoy.to_card(FolderTarget(card), self.v, "http://h:8080")
        with open(os.path.join(card, *convoy.FILE.split("/"))) as f:
            got = json.load(f)
        self.assertNotIn("join", got)
        self.assertNotIn("start_key", got)
        # a host's start key goes with that host only
        convoy.set_start_key("http://h:8080/", "sk-1")
        self.assertEqual(convoy.start_key("http://h:8080"), "sk-1")
        convoy.to_card(FolderTarget(card), self.v, "http://h:8080")
        with open(os.path.join(card, *convoy.FILE.split("/"))) as f:
            self.assertEqual(json.load(f)["start_key"], "sk-1")
        convoy.to_card(FolderTarget(card), self.v, "http://other:8080")
        with open(os.path.join(card, *convoy.FILE.split("/"))) as f:
            self.assertNotIn("start_key", json.load(f))
        convoy.set_start_key("http://h:8080", "")
        self.assertEqual(convoy.start_key("http://h:8080"), "")


if __name__ == "__main__":
    unittest.main()
