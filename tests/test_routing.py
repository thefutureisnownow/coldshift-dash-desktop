import datetime
import os
import shutil
import struct
import tempfile
import unittest
from unittest import mock

from dashsync import maps, routing
from dashsync.transport import FolderTarget

UTC = datetime.timezone.utc


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def map_with_bbox(min_lat, min_lon, max_lat, max_lon, size=200):
    head = maps.MAGIC + struct.pack(">iiqq", 100, 5, size, 0) + struct.pack(
        ">iiii", int(min_lat * 1e6), int(min_lon * 1e6), int(max_lat * 1e6), int(max_lon * 1e6))
    return head + b"\0" * (size - len(head))


class Resp:
    def __init__(self, body, modified):
        self.body = body
        self.headers = {"Content-Length": str(len(body)), "Last-Modified": modified}

    def read(self, n=-1):
        out, self.body = self.body[:n], self.body[n:]
        return out


class RoutingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        env = {"DASHSYNC_CONFIG": os.path.join(self.tmp, "config"), "DASHSYNC_CACHE": os.path.join(self.tmp, "cache")}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        os.makedirs(os.path.join(self.tmp, "card"))
        self.card = FolderTarget(os.path.join(self.tmp, "card"))
        self.now = datetime.datetime(2026, 10, 31, 1, 3, tzinfo=UTC)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tile_names(self):
        self.assertEqual(routing.tile_name(-34.03, 23.05), "E20_S35")      # Knysna
        self.assertEqual(routing.tile_name(-33.92, 18.42), "E15_S35")      # Cape Town
        self.assertEqual(routing.tile_name(51.5, -0.12), "W5_N50")         # London
        self.assertEqual(routing.tiles_for_bbox(-34.5, 18.0, -33.5, 23.5), ["E15_S35", "E20_S35"])

    def test_map_bbox_from_header(self):
        write(os.path.join(self.tmp, "za.map"), map_with_bbox(-47.68493, 15.89606, -22.01736, 39.34259))
        bbox = routing.map_bbox(os.path.join(self.tmp, "za.map"))
        self.assertAlmostEqual(bbox[0], -47.68493)
        self.assertAlmostEqual(bbox[3], 39.34259)

    def _region(self):
        write(os.path.join(self.tmp, "cache", "za.map"), map_with_bbox(-34.5, 18.0, -33.5, 23.5))
        with mock.patch.object(maps, "remote_info", return_value={"bytes": 200, "modified": self.now}):
            maps.choose("africa/za.map")

    def test_sync_downloads_copies_and_removes_old_tiles(self):
        self._region()
        server = {"E15_S35": {"bytes": 10, "modified": self.now}, "E20_S35": {"bytes": 7, "modified": self.now},
                  "E25_S35": {"bytes": 5, "modified": self.now}}
        bodies = {"E15_S35": b"a" * 10, "E20_S35": b"b" * 7}
        write(os.path.join(self.tmp, "card", "coldshift.dash", "routing", "W5_N50.rd5"), b"old")

        def get(url, headers=None, timeout=30):
            return Resp(bodies[url.rsplit("/", 1)[1][:-4]], "Sat, 31 Oct 2026 01:03:00 GMT")

        with mock.patch.object(routing, "server_tiles", return_value=server), mock.patch.object(maps, "_get", side_effect=get):
            r = routing.sync(self.card)
            self.assertEqual((r["tiles"], r["downloaded"], r["copied"], r["removed"]), (2, 2, 2, 1))
            self.assertEqual(sorted(e.name for e in routing.installed(self.card)), ["E15_S35.rd5", "E20_S35.rd5"])
            r = routing.sync(self.card)          # nothing new
            self.assertEqual((r["downloaded"], r["copied"], r["removed"]), (0, 0, 0))

    def test_only_a_much_newer_server_tile_is_fetched_again(self):
        self._region()
        info = {"bytes": 7, "modified": self.now}
        with mock.patch.object(maps, "_get", return_value=Resp(b"b" * 7, "Sat, 31 Oct 2026 01:03:00 GMT")):
            routing.download("E20_S35", info)
        self.assertIsNotNone(routing.cached("E20_S35", {"bytes": 7, "modified": self.now + datetime.timedelta(days=1)}))
        self.assertIsNone(routing.cached("E20_S35", {"bytes": 7, "modified": self.now + datetime.timedelta(days=31)}))

    def test_incomplete_download_is_rejected(self):
        with mock.patch.object(maps, "_get", return_value=Resp(b"b" * 5, "Sat, 31 Oct 2026 01:03:00 GMT")):
            with self.assertRaises(RuntimeError):
                routing.download("E20_S35", {"bytes": 7, "modified": self.now})
        self.assertIsNone(routing.cached("E20_S35", None))


if __name__ == "__main__":
    unittest.main()
