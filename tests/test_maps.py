import datetime
import email.utils
import io
import json
import os
import shutil
import struct
import tempfile
import unittest
from unittest import mock

from dashsync import maps, paths
from dashsync.transport import FolderTarget, parse_df_free

UTC = datetime.timezone.utc
MAPS = "coldshift.dash/maps"


def map_bytes(size, written):
    """A file that passes maps.check: magic, header size, version, total size, creation date."""
    head = maps.MAGIC + struct.pack(">iiqq", 100, 5, size, int(written.timestamp() * 1000))
    return head + b"\0" * (size - len(head))


def read(path):
    with open(path, "rb") as f:
        return f.read()


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class FakeResponse:
    def __init__(self, body, status=200, modified=None):
        self.body, self.status = io.BytesIO(body), status
        self.headers = {"Content-Length": str(len(body))}
        if modified:
            self.headers["Last-Modified"] = email.utils.format_datetime(modified, usegmt=True)

    def read(self, n=-1):
        return self.body.read(n)


class MapsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        env = {"DASHSYNC_CONFIG": os.path.join(self.tmp, "config"), "DASHSYNC_CACHE": os.path.join(self.tmp, "cache")}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        self.card = os.path.join(self.tmp, "card")
        os.makedirs(os.path.join(self.card, MAPS))
        self.t = FolderTarget(self.card)
        self.old = datetime.datetime(2026, 7, 15, 21, 35, tzinfo=UTC)
        self.new = datetime.datetime(2026, 10, 20, 9, 0, tzinfo=UTC)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cache(self, name, data):
        write(os.path.join(paths.cache_dir(), name), data)
        return os.path.join(paths.cache_dir(), name)

    def test_header_date_and_newer(self):
        p = self.cache("a.map", map_bytes(200, self.old))
        self.assertEqual(maps.header_date(p), self.old)
        self.assertTrue(maps.is_newer({"modified": self.new}, p))
        # the server stamps its copy minutes after the writer: that is the same build
        self.assertFalse(maps.is_newer({"modified": self.old + datetime.timedelta(minutes=3)}, p))
        self.assertFalse(maps.is_newer(None, p))

    def test_find_prefers_file_name(self):
        catalog = [{"name": n.split("/")[-1], "path": n, "dir": False, "approx_bytes": 1} for n in
                   ("africa/lesotho.map", "africa/south-africa-and-lesotho.map", "africa/south-sudan.map",
                    "europe/germany/baden-wuerttemberg.map")]
        write(os.path.join(paths.cache_dir(), "catalog.json"),
              json.dumps({"fetched": datetime.datetime.now(UTC).timestamp(), "maps": catalog}).encode())
        with mock.patch.object(maps, "list_region", side_effect=AssertionError("crawled despite a fresh catalog")):
            hits = maps.find("South Africa")
            self.assertEqual([e["path"] for e in hits], ["africa/south-africa-and-lesotho.map", "africa/south-sudan.map"])
            self.assertEqual(maps.best(hits, "South Africa")["path"], "africa/south-africa-and-lesotho.map")
            self.assertIsNone(maps.best(maps.find("lesotho"), "lesotho"))    # two file names match: ask
            hits = maps.find("africa")
            self.assertEqual(len(hits), 3)
            self.assertEqual(hits[0]["path"], "africa/south-africa-and-lesotho.map")
            self.assertEqual([e["path"] for e in maps.find("germany baden")], ["europe/germany/baden-wuerttemberg.map"])
            self.assertEqual(maps.find("nowhere"), [])

    def test_install_updates_same_name_in_place(self):
        write(os.path.join(self.card, MAPS, "za.map"), map_bytes(200, self.old))
        local = self.cache("za.map", map_bytes(300, self.new))
        with self.assertRaises(SystemExit):
            maps.install(self.t, local, MAPS)
        self.assertEqual(maps.install(self.t, local, MAPS, replace_older=True), "updated za.map")
        self.assertEqual([(e.name, e.size) for e in maps.installed(self.t, MAPS)], [("za.map", 300)])
        self.assertEqual(maps.install(self.t, local, MAPS), "already installed")

    def test_install_replaces_other_map_only_when_asked(self):
        write(os.path.join(self.card, MAPS, "swaziland.map"), map_bytes(100, self.old))
        local = self.cache("za.map", map_bytes(300, self.new))
        with self.assertRaises(SystemExit):
            maps.install(self.t, local, MAPS)
        self.assertEqual([e.name for e in maps.installed(self.t, MAPS)], ["swaziland.map"])
        maps.install(self.t, local, MAPS, replace=True)
        self.assertEqual([e.name for e in maps.installed(self.t, MAPS)], ["za.map"])

    def test_sync_fetches_newer_build_then_swaps_card(self):
        with mock.patch.object(maps, "remote_info", return_value={"bytes": 300, "modified": self.new}):
            maps.choose("africa/za")
        self.assertEqual(maps.chosen(), "africa/za.map")
        self.cache("za.map", map_bytes(200, self.old))
        write(os.path.join(self.card, MAPS, "za.map"), map_bytes(200, self.old))
        write(os.path.join(self.card, MAPS, "swaziland.map"), map_bytes(100, self.old))
        with mock.patch.object(maps, "remote_info", return_value={"bytes": 300, "modified": self.new}), \
                mock.patch.object(maps, "_get", return_value=FakeResponse(map_bytes(300, self.new), modified=self.new)) as get:
            msg = maps.sync(self.t, MAPS)
        get.assert_called_once()
        self.assertEqual(msg, "updated za.map (replaced swaziland.map)")
        self.assertEqual([(e.name, e.size) for e in maps.installed(self.t, MAPS)], [("za.map", 300)])
        self.assertEqual(maps.header_date(maps.cached("africa/za.map")), self.new)

    def test_tell_app(self):
        class Phone:
            kind = "adb"

            def __init__(self, reply):
                self.reply, self.sent = reply, []

            def notify_synced(self, what):
                self.sent.append(what)
                return self.reply

        p = Phone("reloaded maps")
        self.assertEqual(maps.tell_app(p, "installed za.map"), "the app reloaded maps")
        self.assertEqual(p.sent, [["maps"]])
        self.assertIn("not running", maps.tell_app(Phone(None), "updated za.map"))
        quiet = Phone("reloaded maps")
        self.assertEqual(maps.tell_app(quiet, "already installed"), "")
        self.assertEqual(quiet.sent, [])
        self.assertEqual(maps.tell_app(self.t, "installed za.map"), "")     # card reader: nothing to tell

    def test_sync_without_region(self):
        with self.assertRaises(SystemExit):
            maps.sync(self.t, MAPS)

    def test_download_keeps_current_cache(self):
        self.cache("za.map", map_bytes(200, self.new))
        with mock.patch.object(maps, "_get", side_effect=AssertionError("downloaded a current map")):
            maps.download("africa/za.map", remote={"bytes": 200, "modified": self.new})

    def test_resume_restarts_when_server_file_changed(self):
        body = map_bytes(300, self.new)
        part = self.cache("za.map.part", b"stale bytes of an older build")
        write(part + ".json", json.dumps({"last_modified": "Wed, 15 Jul 2026 21:37:27 GMT"}).encode())
        with mock.patch.object(maps, "_get", return_value=FakeResponse(body, 200, self.new)) as get:
            path = maps.download("africa/za.map")
        headers = get.call_args[0][1]
        self.assertEqual(headers["If-Range"], "Wed, 15 Jul 2026 21:37:27 GMT")
        self.assertEqual(read(path), body)
        self.assertFalse(os.path.exists(part + ".json"))

    def test_resume_appends_when_server_file_unchanged(self):
        body = map_bytes(300, self.new)
        part = self.cache("za.map.part", body[:120])
        write(part + ".json", json.dumps({"last_modified": "x"}).encode())
        with mock.patch.object(maps, "_get", return_value=FakeResponse(body[120:], 206)) as get:
            path = maps.download("africa/za.map")
        self.assertEqual(get.call_args[0][1]["Range"], "bytes=120-")
        self.assertEqual(read(path), body)

    def test_resume_without_metadata_starts_over(self):
        body = map_bytes(300, self.new)
        self.cache("za.map.part", b"from an older version of the tool")
        with mock.patch.object(maps, "_get", return_value=FakeResponse(body)) as get:
            path = maps.download("africa/za.map")
        self.assertNotIn("Range", get.call_args[0][1])
        self.assertEqual(read(path), body)

    def test_download_tries_again_after_a_dropped_connection(self):
        import urllib.error
        calls = []

        def flaky(path, progress, remote):
            calls.append(path)
            if len(calls) < 3:
                raise TimeoutError("The read operation timed out")
            return "done"
        with mock.patch.object(maps, "_download", flaky):
            self.assertEqual(maps.download("africa/x.map", pause=0), "done")
        self.assertEqual(len(calls), 3)
        # it gives up in the end, and does not ask again when the server answered with an error
        with mock.patch.object(maps, "_download", side_effect=TimeoutError("stalled")) as m:
            with self.assertRaises(TimeoutError):
                maps.download("africa/x.map", pause=0)
        self.assertEqual(m.call_count, maps.RETRIES + 1)
        gone = urllib.error.HTTPError("u", 404, "Not Found", None, None)
        with mock.patch.object(maps, "_download", side_effect=gone) as m:
            with self.assertRaises(urllib.error.HTTPError):
                maps.download("africa/x.map", pause=0)
        self.assertEqual(m.call_count, 1)

    def test_android_df(self):
        out = ("Filesystem               Size     Used     Free   Blksize\n"
               "/storage/sdcard1        29.7G     7.3G    22.4G   32768\n")
        self.assertEqual(parse_df_free(out, "/storage/sdcard1"), int(22.4 * 1024 ** 3))
        self.assertEqual(parse_df_free("/storage/sdcard1 1G 1G 512M 4096", "/storage/sdcard1/"), 512 * 1024 ** 2)
        self.assertIsNone(parse_df_free("df: /storage/sdcard1: No such file", "/storage/sdcard1"))

    @unittest.skipIf(os.name == "nt" or os.geteuid() == 0, "needs POSIX permissions and a non-root user")
    def test_unwritable_settings_give_a_fix(self):
        os.chmod(paths.config_dir(), 0o500)
        try:
            with self.assertRaises(SystemExit) as cm:
                paths.save_config({"map_region": "x.map"})
            self.assertIn("chown", str(cm.exception))
        finally:
            os.chmod(paths.config_dir(), 0o700)


if __name__ == "__main__":
    unittest.main()
