import json
import unittest
from pathlib import Path

from beamng_catalog.categories import category_page_url, resource_page_url
from beamng_catalog.crawl import ROBOTS_URL, CrawlError, update_catalog
from beamng_catalog.robots import parse_robots

FIXTURES = Path(__file__).parent / "fixtures"
ROBOTS = "User-agent: *\nDisallow: /library\n"


class FakeClient:
    def __init__(self, pages):
        self.interval = 1.0
        self.pages = pages
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if url not in self.pages:
            raise CrawlError(f"unexpected url {url}")
        return self.pages[url]


def _tyrelabs_mod():
    return {
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


class CrawlTest(unittest.TestCase):
    def test_robots_disallow_does_not_touch_the_catalog(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            original = {"version": 1, "generated": 1, "count": 1, "source": "seed", "mods": [_tyrelabs_mod()]}
            (directory / "catalog.json").write_text(json.dumps(original), encoding="utf-8")
            before = (directory / "catalog.json").read_bytes()
            client = FakeClient({ROBOTS_URL: "User-agent: *\nDisallow: /resources\n"})
            code = update_catalog(directory, None, "incremental", client=client, categories=[(3, "land", "Land")])
            self.assertEqual(code, 1)
            self.assertEqual((directory / "catalog.json").read_bytes(), before)
            self.assertFalse((directory / "trending.json").exists())

    def test_incremental_merges_one_live_fixture_and_keeps_the_row(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            catalog = {
                "version": 1,
                "generated": 1791781258,
                "count": 1,
                "source": "seed",
                "mods": [_tyrelabs_mod()],
            }
            (directory / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
            land = category_page_url("land", 3, 1)
            detail = resource_page_url("tyrelabs", 39641)
            client = FakeClient(
                {
                    ROBOTS_URL: ROBOTS,
                    land: (FIXTURES / "listing_land.html").read_text(encoding="utf-8"),
                    detail: (FIXTURES / "resource_tyrelabs.html").read_text(encoding="utf-8"),
                }
            )
            code = update_catalog(
                directory,
                None,
                "incremental",
                now=1791782000,
                max_details=1,
                categories=[(3, "land", "Land")],
                client=client,
            )
            self.assertEqual(code, 0, client.urls)
            self.assertIn(detail, client.urls)
            saved = json.loads((directory / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["count"], 1)
            mod = saved["mods"][0]
            self.assertEqual(mod["download_count"], 86)
            self.assertEqual(mod["filesize"], 1350784)
            self.assertEqual(mod["filename"], "TyreLab.zip")
            self.assertEqual(mod["resource_id"], 39641)
            self.assertEqual(mod["mentions_versions"], ["0.35", "0.39"])
            self.assertTrue(mod["screenshots"])
            self.assertEqual(mod["version"], "1.0")
            self.assertEqual(mod["first_release"], 1791552358)
            self.assertIsNone(mod["forum_thread"])
            self.assertEqual(mod["requires"], [])
            self.assertEqual(mod["requires_tagid"], [])

    def test_full_sweep_drops_mods_missing_from_the_listing(self):
        from tempfile import TemporaryDirectory

        listing = """
        <div class="PageNav" data-last="1" data-page="1"></div>
        <ol>
          <li class="resourceListItem" id="resource-7">
            <h3 class="title">
              <a href="resources/kept-mod.7/">Kept Truck Pack</a>
              <span class="version">2.0</span>
            </h3>
            <div class="resourceDetails muted">
              <a href="resources/authors/ada.1/">ada</a>
              <abbr class="DateTime" data-time="1700000000">Jan 1, 2024</abbr>
              <a href="resources/categories/land.3/">Land</a>
            </div>
            <div class="tagLine">A gavril truck pack</div>
            <div class="listBlock resourceStats">
              <div class="rating"><span class="Number">5</span><span class="Hint">1 rating</span></div>
              <dl class="resourceUpdated"><dt>Updated:</dt><dd><abbr class="DateTime" data-time="1700000000"></abbr></dd></dl>
            </div>
          </li>
        </ol>
        """
        resource = """
        <html><head><link rel="canonical" href="https://www.beamng.com/resources/kept-mod.7/" /></head>
        <body>
          <div class="resourceInfo">
            <h1>Kept Truck Pack <span class="muted">2.0</span></h1>
            <p class="tagLine">A gavril truck pack</p>
          </div>
          <a href="resources/kept-mod.7/download?version=99">Download Now <small>10 KB .zip</small></a>
          <div><h3>Information</h3>
            <dl class="author"><dt>Author:</dt><dd><a href="resources/authors/ada.1/">ada</a></dd></dl>
            <dl><dt>Unique ID:</dt><dd>KEEPME</dd></dl>
            <dl class="firstRelease"><dt>First Release:</dt><dd><abbr class="DateTime" data-time="1600000000"></abbr></dd></dl>
            <dl class="lastUpdate"><dt>Last Update:</dt><dd><abbr class="DateTime" data-time="1700000000"></abbr></dd></dl>
            <dl class="resourceCategory"><dt>Category:</dt><dd><a href="resources/categories/land.3/">Land</a></dd></dl>
          </div>
          <div><h3>Version 2.0</h3>
            <dl class="versionDownloadCount"><dt>Downloads:</dt><dd>4</dd></dl>
          </div>
          <div class="updateContainer"><ol>
            <li class="resourceUpdate"><blockquote class="messageText ugc baseHtml">
              Requires <a href="https://www.beamng.com/resources/other.20/">other</a>.
              Made for 0.37.
            </blockquote></li>
          </ol></div>
        </body></html>
        """
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            catalog = {
                "version": 1,
                "generated": 1,
                "count": 2,
                "source": "seed",
                "mods": [
                    {
                        "tagid": "KEEPME",
                        "title": "Kept",
                        "prefix_title": "",
                        "tag_line": "",
                        "username": "ada",
                        "cats": [3],
                        "category_title": "Land",
                        "last_update": 1,
                        "resource_date": 1,
                        "download_count": 1,
                        "rating_avg": 0,
                        "rating_count": 0,
                        "filesize": 1,
                        "filename": "kept.zip",
                        "path": "KEEPME/99/",
                    },
                    {
                        "tagid": "DROPME",
                        "title": "Gone",
                        "prefix_title": "",
                        "tag_line": "",
                        "username": "ada",
                        "cats": [3],
                        "category_title": "Land",
                        "last_update": 1,
                        "resource_date": 1,
                        "download_count": 1,
                        "rating_avg": 0,
                        "rating_count": 0,
                        "filesize": 1,
                        "filename": "gone.zip",
                        "path": "DROPME/5/",
                    },
                ],
            }
            (directory / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
            client = FakeClient(
                {
                    ROBOTS_URL: ROBOTS,
                    category_page_url("land", 3, 1): listing,
                    resource_page_url("kept-mod", 7): resource,
                }
            )
            code = update_catalog(
                directory,
                None,
                "full",
                now=1700001000,
                categories=[(3, "land", "Land")],
                client=client,
            )
            self.assertEqual(code, 0, client.urls)
            saved = json.loads((directory / "catalog.json").read_text(encoding="utf-8"))
            tags = [mod["tagid"] for mod in saved["mods"]]
            self.assertEqual(tags, ["KEEPME"])
            kept = saved["mods"][0]
            self.assertEqual(kept["requires"], [20])
            self.assertEqual(kept["requires_tagid"], [None])
            self.assertEqual(kept["mentions_versions"], ["0.37"])
            self.assertEqual(kept["version"], "2.0")
            self.assertEqual(kept["first_release"], 1600000000)
            self.assertIn("brand:gavril", kept["tags"])
            self.assertIn("vehicle:truck", kept["tags"])
            self.assertIn("pack", kept["tags"])
            self.assertIsNone(kept["forum_thread"])


class RobotsTest(unittest.TestCase):
    def test_beamng_robots_allows_resources_and_blocks_library(self):
        robots = parse_robots("User-agent: *\nDisallow: /library\n")
        self.assertTrue(robots.allows("/resources/"))
        self.assertTrue(robots.allows("/resources/categories/land.3/"))
        self.assertFalse(robots.allows("/library"))
        self.assertFalse(robots.allows("/library/hidden"))

    def test_crawl_delay(self):
        robots = parse_robots("User-agent: *\nDisallow:\nCrawl-delay: 3\n")
        self.assertTrue(robots.allows("/resources/"))
        self.assertEqual(robots.delay, 3)


if __name__ == "__main__":
    unittest.main()
