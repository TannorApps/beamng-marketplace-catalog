import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from beamng_catalog.parse import (
    choose_filesize,
    dependency_resource_ids,
    detect_tags,
    human_size,
    mentions_versions,
    parse_listing_page,
    parse_resource_page,
)

FIXTURES = Path(__file__).parent / "fixtures"


class ListingParserTest(unittest.TestCase):
    def test_land_page_parses_prefixed_and_plain_items(self):
        html = (FIXTURES / "listing_land.html").read_text(encoding="utf-8")
        parsed = parse_listing_page(html, page_category_id=3, page_category_title="Land")
        self.assertEqual(parsed["last_page"], 21)
        self.assertEqual(len(parsed["items"]), 20)
        first = parsed["items"][0]
        self.assertEqual(first["forum_id"], 39641)
        self.assertEqual(first["slug"], "tyrelabs")
        self.assertEqual(first["title"], "Tyrelabs")
        self.assertEqual(first["prefix_title"], "Beta")
        self.assertEqual(first["version"], "1.0")
        self.assertEqual(first["username"], "giogoesinsane")
        self.assertEqual(first["cats"], [3])
        self.assertEqual(first["category_title"], "Land")
        self.assertEqual(first["tag_line"], "plug and play")
        self.assertEqual(first["rating_avg"], 1.125)
        self.assertEqual(first["rating_count"], 8)
        self.assertEqual(first["listing_downloads"], 4354)
        self.assertEqual(first["last_update"], 1791552358)
        self.assertEqual(first["resource_date"], 1791552358)
        self.assertTrue(first["thumb"].startswith("https://www.beamng.com/data/resource_icons/"))
        banana = next(item for item in parsed["items"] if item["forum_id"] == 39636)
        self.assertEqual(banana["title"], "Banana Car")
        self.assertEqual(banana["prefix_title"], "")
        self.assertEqual(banana["last_update"], 1791206160)
        self.assertEqual(banana["cats"], [3])

    def test_category_fallback_is_not_required_when_the_item_has_one(self):
        html = (FIXTURES / "listing_land.html").read_text(encoding="utf-8")
        parsed = parse_listing_page(html)
        banana = next(item for item in parsed["items"] if item["forum_id"] == 39636)
        self.assertEqual(banana["cats"], [])

    def test_second_page_separates_release_and_update(self):
        html = (FIXTURES / "listing_land_page2.html").read_text(encoding="utf-8")
        parsed = parse_listing_page(html, page_category_id=3, page_category_title="Land")
        brutto = next(item for item in parsed["items"] if item["forum_id"] == 23325)
        self.assertEqual(brutto["resource_date"], 1658733840)
        self.assertEqual(brutto["last_update"], 1790073660)
        self.assertNotEqual(brutto["resource_date"], brutto["last_update"])

    def test_single_page_category(self):
        html = (FIXTURES / "listing_boats.html").read_text(encoding="utf-8")
        parsed = parse_listing_page(html, page_category_id=6, page_category_title="Boats")
        self.assertEqual(parsed["last_page"], 1)
        self.assertEqual(len(parsed["items"]), 13)
        self.assertEqual(parsed["items"][0]["prefix_title"], "Experimental")
        self.assertEqual(parsed["items"][0]["cats"], [6])


class ResourceParserTest(unittest.TestCase):
    def test_tyrelabs_resource_page(self):
        html = (FIXTURES / "resource_tyrelabs.html").read_text(encoding="utf-8")
        detail = parse_resource_page(html)
        self.assertEqual(detail["tagid"], "M2YNFTLV4")
        self.assertEqual(detail["forum_id"], 39641)
        self.assertEqual(detail["version_id"], 73278)
        self.assertEqual(detail["title"], "Tyrelabs")
        self.assertEqual(detail["prefix_title"], "Beta")
        self.assertEqual(detail["version"], "1.0")
        self.assertEqual(detail["username"], "giogoesinsane")
        self.assertEqual(detail["cats"], [3])
        self.assertEqual(detail["category_title"], "Land")
        self.assertEqual(detail["download_count"], 86)
        self.assertEqual(detail["first_release"], 1791552358)
        self.assertEqual(detail["last_update"], 1791552358)
        self.assertEqual(detail["mentions_versions"], ["0.35", "0.39"])
        self.assertEqual(detail["requires"], [])
        self.assertEqual(detail["tags"], [])
        self.assertIsNone(detail["forum_thread"])
        self.assertTrue(detail["screenshots"])
        self.assertTrue(detail["screenshots"][0].startswith("https://www.beamng.com/data/attachments/"))
        self.assertTrue(detail["screenshots"][0].endswith(".jpg"))
        self.assertIn("1.3 MB", detail["filesize_label"])

    def test_polish_roads_thread_screenshots_and_version_mention(self):
        html = (FIXTURES / "resource_polish.html").read_text(encoding="utf-8")
        detail = parse_resource_page(html)
        self.assertEqual(detail["tagid"], "MN2D9XPFH")
        self.assertEqual(detail["version"], "3.3")
        self.assertEqual(detail["first_release"], 1537456140)
        self.assertEqual(
            detail["forum_thread"],
            "https://www.beamng.com/threads/polish-roads-3-3-discussion.89413/",
        )
        self.assertEqual(detail["mentions_versions"], ["0.39"])
        self.assertNotIn(36648, detail["requires"])
        self.assertIn("map", detail["tags"])
        self.assertNotIn("pack", detail["tags"])
        self.assertNotIn("vehicle:semi", detail["tags"])
        self.assertGreaterEqual(len(detail["screenshots"]), 8)
        self.assertTrue(all(url.startswith("https://www.beamng.com/") for url in detail["screenshots"]))
        self.assertTrue(all("/attachments/" in url and url.split("?", 1)[0].endswith(".jpg") for url in detail["screenshots"]))


class DependencyAndTagTest(unittest.TestCase):
    def test_dependency_window_and_version_mentions(self):
        html = (FIXTURES / "description_dependencies.html").read_text(encoding="utf-8")
        node = BeautifulSoup(html, "html.parser").select_one("blockquote")
        self.assertEqual(dependency_resource_ids(node, self_id=39641), [12345, 77])
        self.assertEqual(mentions_versions(node.get_text(" ", strip=True)), ["0.35", "0.38", "0.39"])

    def test_version_patch_collapses_to_two_components(self):
        self.assertEqual(mentions_versions("works on 0.39.4 and also 0.39"), ["0.39"])
        self.assertEqual(mentions_versions("score 4.39 and year 10.39"), [])

    def test_keyword_tags(self):
        tags = detect_tags(
            title="Gavril D-Series Truck Pack",
            tag_line="",
            category_title="Land",
            category_ids=[3],
        )
        self.assertEqual(tags, ["brand:gavril", "vehicle:truck", "pack"])
        self.assertEqual(
            detect_tags(title="Carpet cleaner", category_title="Props", category_ids=[5]),
            [],
        )
        self.assertEqual(
            detect_tags(title="Semi-realistic map", category_title="Terrains, Levels, Maps", category_ids=[9]),
            ["map"],
        )
        self.assertIn("vehicle:semi", detect_tags(title="American semi truck"))
        self.assertIn(
            "map",
            detect_tags(title="Polish Roads", category_title="Terrains, Levels, Maps", category_ids=[9]),
        )
        self.assertIn(
            "brand:ibishu",
            detect_tags(title="Custom", description="Built for the Ibishu Covet."),
        )
        self.assertIn("vehicle:boat", detect_tags(title="Carrier", category_title="Boats", category_ids=[6]))


class FileSizeTest(unittest.TestCase):
    def test_rounded_label_keeps_exact_seed_size(self):
        self.assertEqual(human_size(1350784), "1.3 MB")
        self.assertEqual(choose_filesize(1350784, "1.3 MB .zip"), 1350784)
        self.assertNotEqual(choose_filesize(1350784, "2.0 MB .zip"), 1350784)
        self.assertEqual(choose_filesize(None, "1.3 MB .zip"), 1363149)


if __name__ == "__main__":
    unittest.main()
