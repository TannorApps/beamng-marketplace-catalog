import gzip
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from beamng_catalog.catalog import (
    Index,
    build_trending,
    dump_catalog,
    load_seed,
    prune_snapshots,
    publication_ok,
    publish_seed,
    resolve_requires,
    upsert_detail,
    write_snapshot,
)
from beamng_catalog.parse import parse_resource_page

ROOT = Path(__file__).parents[1]
SEED = ROOT / "seed" / "catalog.json.gz"
FIXTURES = Path(__file__).parent / "fixtures"


class SeedTest(unittest.TestCase):
    def test_seed_json_round_trip(self):
        raw = gzip.open(SEED, "rb").read()
        catalog = load_seed(SEED)
        self.assertEqual(catalog["count"], 8611)
        self.assertEqual(catalog["source"], "seed")
        self.assertEqual(len(catalog["mods"]), 8611)
        self.assertEqual(dump_catalog(catalog), raw)

    def test_publish_seed_keeps_item_bytes_and_writes_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            publish_seed(directory, SEED)
            self.assertEqual((directory / "catalog.json").read_bytes(), gzip.open(SEED, "rb").read())
            meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["count"], 8611)
            self.assertIn("tagid", meta["schema"]["required"])
            for field in (
                "first_release",
                "version",
                "screenshots",
                "forum_thread",
                "mentions_versions",
                "requires",
                "requires_tagid",
                "tags",
            ):
                self.assertIn(field, meta["schema"]["optional"])
            trending = json.loads((directory / "trending.json").read_text(encoding="utf-8"))
            self.assertEqual(trending["periods"]["day"]["label"], "estimated: not enough history")
            self.assertFalse(trending["periods"]["all_time"]["estimated"])
            self.assertEqual(len(trending["periods"]["all_time"]["items"]), 200)
            self.assertTrue((directory / "snapshots" / "2026-10-12.json").exists())


class MergeTest(unittest.TestCase):
    def test_match_on_tagid_preserves_exact_filename_and_size(self):
        html = (FIXTURES / "resource_tyrelabs.html").read_text(encoding="utf-8")
        detail = parse_resource_page(html)
        mod = {
            "tagid": "M2YNFTLV4",
            "title": "Tyrelabs",
            "prefix_title": "Beta",
            "tag_line": "plug and play",
            "username": "giogoesinsane",
            "cats": [3],
            "category_title": "Land",
            "last_update": 1791552358,
            "resource_date": 1791552358,
            "download_count": 83,
            "rating_avg": 1.14286,
            "rating_count": 7,
            "filesize": 1350784,
            "filename": "TyreLab.zip",
            "path": "M2YNFTLV4/73278/",
        }
        index = Index([mod])
        upsert_detail(index, detail)
        self.assertEqual(len(index.mods), 1)
        self.assertEqual(mod["download_count"], 86)
        self.assertEqual(mod["filesize"], 1350784)
        self.assertEqual(mod["filename"], "TyreLab.zip")
        self.assertEqual(mod["resource_id"], 39641)
        self.assertEqual(mod["version"], "1.0")
        self.assertEqual(mod["first_release"], 1791552358)
        self.assertEqual(mod["mentions_versions"], ["0.35", "0.39"])
        self.assertEqual(mod["path"], "M2YNFTLV4/73278/")

    def test_match_on_path_version_id(self):
        html = (FIXTURES / "resource_tyrelabs.html").read_text(encoding="utf-8")
        detail = parse_resource_page(html)
        mod = {
            "tagid": "STALE",
            "title": "Old",
            "prefix_title": "",
            "tag_line": "",
            "username": "",
            "cats": [],
            "category_title": "",
            "last_update": 1,
            "resource_date": 1,
            "download_count": 1,
            "rating_avg": 0,
            "rating_count": 0,
            "filesize": 10,
            "filename": "keep.zip",
            "path": "STALE/73278/",
        }
        index = Index([mod])
        upsert_detail(index, detail)
        self.assertEqual(len(index.mods), 1)
        self.assertEqual(mod["tagid"], "M2YNFTLV4")
        self.assertEqual(mod["path"], "M2YNFTLV4/73278/")
        self.assertEqual(mod["filename"], "keep.zip")
        self.assertIsNone(index.by_tag.get("STALE"))

    def test_requires_tagid_fills_in_when_the_dependency_is_known(self):
        mods = [
            {"tagid": "AAA", "resource_id": 10, "requires": [20, 30]},
            {"tagid": "BBB", "resource_id": 20},
        ]
        resolve_requires(mods, {})
        self.assertEqual(mods[0]["requires_tagid"], ["BBB", None])
        resolve_requires(mods, {"30": {"tagid": "CCC"}})
        self.assertEqual(mods[0]["requires_tagid"], ["BBB", "CCC"])


class SafetyTest(unittest.TestCase):
    def test_publication_guard(self):
        self.assertFalse(publication_ok(10, 0, True)[0])
        self.assertFalse(publication_ok(10, 9, False)[0])
        self.assertTrue(publication_ok(10, 10, False)[0])
        self.assertTrue(publication_ok(10, 6, True)[0])
        self.assertFalse(publication_ok(10, 4, True)[0])


class TrendingTest(unittest.TestCase):
    def _mods(self):
        return [
            {"tagid": "A", "title": "A", "username": "a", "category_title": "Land", "download_count": 10},
            {"tagid": "B", "title": "B", "username": "b", "category_title": "Air", "download_count": 50},
        ]

    def test_not_enough_history_is_labeled(self):
        generated = int(datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp())
        snapshots = [(date(2026, 10, 12), {"A": 10, "B": 50})]
        trending = build_trending(self._mods(), snapshots, generated)
        self.assertEqual(trending["periods"]["week"]["label"], "estimated: not enough history")
        self.assertTrue(trending["periods"]["week"]["estimated"])
        self.assertIsNone(trending["periods"]["week"]["items"][0]["delta"])
        self.assertEqual(trending["periods"]["week"]["items"][0]["tagid"], "B")
        self.assertEqual(trending["periods"]["all_time"]["items"][0]["delta"], 50)
        self.assertFalse(trending["periods"]["all_time"]["estimated"])

    def test_measured_day_and_extrapolated_week(self):
        generated = int(datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp())
        snapshots = [
            (date(2026, 10, 11), {"A": 7, "B": 40}),
            (date(2026, 10, 12), {"A": 10, "B": 50}),
        ]
        trending = build_trending(self._mods(), snapshots, generated)
        day = {item["tagid"]: item for item in trending["periods"]["day"]["items"]}
        self.assertEqual(trending["periods"]["day"]["label"], "measured")
        self.assertEqual(day["A"]["delta"], 3)
        self.assertFalse(day["A"]["estimated"])
        week = {item["tagid"]: item for item in trending["periods"]["week"]["items"]}
        self.assertEqual(trending["periods"]["week"]["label"], "estimated: extrapolated from shorter history")
        self.assertEqual(week["A"]["delta"], 21)
        self.assertTrue(week["A"]["estimated"])

    def test_snapshot_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            mods = self._mods()
            write_snapshot(directory, mods, int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()))
            write_snapshot(directory, mods, int(datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp()))
            removed = prune_snapshots(directory, date(2026, 10, 12), keep_days=400)
            names = sorted(path.name for path in removed)
            self.assertEqual(names, ["2024-01-01.json"])
            self.assertTrue((directory / "snapshots" / "2026-10-12.json").exists())


if __name__ == "__main__":
    unittest.main()
