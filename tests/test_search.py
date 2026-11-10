import os
import shutil
import sqlite3
import tempfile
import unittest

from dashsync import search
from dashsync.transport import FolderTarget

# a few streets, places and an address around George, as OpenStreetMap XML
OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
  <node id="1" lat="-33.9630" lon="22.4617"><tag k="place" v="town"/><tag k="name" v="George"/>
    <tag k="population" v="157394"/></node>
  <node id="2" lat="-33.9580" lon="22.4480"><tag k="place" v="suburb"/><tag k="name" v="King George Park"/></node>
  <node id="3" lat="-34.0350" lon="23.0470"><tag k="place" v="town"/><tag k="name" v="Knysna"/></node>
  <node id="10" lat="-33.9600" lon="22.4500"/>
  <node id="11" lat="-33.9605" lon="22.4510"/>
  <node id="12" lat="-33.9610" lon="22.4520"/>
  <node id="13" lat="-34.0360" lon="23.0480"/>
  <node id="14" lat="-34.0365" lon="23.0490"/>
  <way id="100"><nd ref="10"/><nd ref="11"/><nd ref="12"/><tag k="highway" v="residential"/>
    <tag k="name" v="York Street"/></way>
  <way id="101"><nd ref="13"/><nd ref="14"/><tag k="highway" v="residential"/><tag k="name" v="York Street"/></way>
  <way id="102"><nd ref="10"/><nd ref="12"/><tag k="highway" v="footway"/><tag k="name" v="Garden Path"/></way>
  <node id="20" lat="-33.9620" lon="22.4600"><tag k="amenity" v="fuel"/><tag k="name" v="Engen Café"/></node>
  <node id="21" lat="-33.9621" lon="22.4601"><tag k="amenity" v="bench"/><tag k="name" v="Bench"/></node>
  <node id="22" lat="-33.9606" lon="22.4511"><tag k="addr:housenumber" v="12"/><tag k="addr:street" v="York Street"/></node>
  <node id="23" lat="-33.9607" lon="22.4512"><tag k="addr:housenumber" v="124"/><tag k="addr:street" v="York Street"/></node>
  <node id="25" lat="-33.9609" lon="22.4519"><tag k="addr:housenumber" v="20"/><tag k="addr:street" v="York Street"/></node>
  <node id="24" lat="-33.9622" lon="22.4602"><tag k="railway" v="tram_stop"/><tag k="name" v="George Stop"/></node>
</osm>
"""


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.osm = os.path.join(self.tmp, "test.osm")
        with open(self.osm, "w", encoding="utf-8") as f:
            f.write(OSM)
        self.db = os.path.join(self.tmp, "test.db")
        self.result = search.build(self.osm, self.db, "africa/test.map", log=lambda s: None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def names(self, text, near=(None, None)):
        return [(r["name"], r["area"]) for r in search.query(self.db, text, near[0], near[1])]

    def test_fold_matches_the_app(self):
        self.assertEqual(search.fold("Église  St-Pierre"), "eglise st pierre")
        self.assertEqual(search.keywords("York Street", "George"), "york street st george")

    def test_kinds_and_areas(self):
        k = self.result["kinds"]
        self.assertEqual((k[search.TOWN], k[search.SUBURB], k[search.STREET], k[search.POI], k[search.ADDRESS]), (2, 1, 2, 1, 3))
        self.assertIn(("York Street", "King George Park, George"), self.names("york"))
        self.assertIn(("York Street", "Knysna"), self.names("york"))

    def test_prefixes_abbreviations_and_accents(self):
        self.assertEqual(self.names("york st geo")[0], ("York Street", "King George Park, George"))
        self.assertEqual(self.names("engen cafe")[0][0], "Engen Café")
        self.assertEqual(self.names("12 york", near=(-33.9607, 22.4512))[0][0], "12 York Street")
        self.assertEqual(self.names("george stop"), [])                # tram stops are left out
        self.assertEqual(self.names("bench"), [])                      # clutter is left out
        self.assertEqual(self.names("garden path"), [])                # footpaths are not streets

    def test_unmapped_number_is_estimated_between_neighbours(self):
        r = search.query(self.db, "16 york street, george", -33.96, 22.45)[0]
        self.assertEqual((r["name"], r["detail"]), ("16 York Street", "Estimated, between 12 and 20"))
        self.assertAlmostEqual(r["lat"], (-33.9606 + -33.9609) / 2, places=5)
        r = search.query(self.db, "13 york street george", -33.96, 22.45)[0]
        self.assertEqual((r["name"], r["detail"]), ("13 York Street", "Estimated, near 12"))      # no odd numbers
        r = search.query(self.db, "8 york street george", -33.96, 22.45)[0]
        self.assertEqual(r["detail"], "Estimated, near 12")
        r = search.query(self.db, "5 york street knysna", -34.03, 23.05)[0]
        self.assertEqual((r["name"], r["detail"], r["area"]), ("York Street", "Number 5 is not mapped", "Knysna"))
        self.assertEqual(search.query(self.db, "12 york street", -33.96, 22.45)[0]["detail"], "")

    def test_nearer_first(self):
        self.assertEqual(self.names("york street", near=(-34.03, 23.05))[0], ("York Street", "Knysna"))
        self.assertEqual(self.names("york street", near=(-33.96, 22.45))[0], ("York Street", "King George Park, George"))

    def test_file_is_readable_by_old_sqlite(self):
        db = sqlite3.connect(self.db)
        try:
            sql = " ".join(r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
            meta = dict(db.execute("SELECT key, value FROM meta"))
            mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            db.close()
        self.assertNotIn("WITHOUT ROWID", sql.upper())
        self.assertNotIn("fts5", sql.lower())
        self.assertEqual(meta["version"], str(search.VERSION))
        self.assertEqual(mode, "delete")
        with open(self.db, "rb") as f:
            head = f.read(100)
        self.assertEqual(head[18:20], b"\x01\x01")              # rollback journal, not WAL (needs 3.7.0)

    def test_sync_copies_once_and_removes_other_regions(self):
        os.makedirs(os.path.join(self.tmp, "card", "coldshift.dash", "search"))
        with open(os.path.join(self.tmp, "card", "coldshift.dash", "search", "old.db"), "wb") as f:
            f.write(b"x")
        card = FolderTarget(os.path.join(self.tmp, "card"))
        prep = lambda region=None, progress=None, log=None: (self.db, False)
        orig, search.prepare = search.prepare, prep
        try:
            r = search.sync(card, log=lambda s: None)
            self.assertEqual((r["copied"], r["removed"]), (True, 1))
            self.assertEqual([e.name for e in search.installed(card)], ["test.db"])
            r = search.sync(card, log=lambda s: None)
            self.assertEqual((r["copied"], r["removed"]), (False, 0))
        finally:
            search.prepare = orig


if __name__ == "__main__":
    unittest.main()
