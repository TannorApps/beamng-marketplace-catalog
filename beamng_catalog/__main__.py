"""Command line for the catalog publisher."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from beamng_catalog.catalog import publish_seed
from beamng_catalog.crawl import ROBOTS_URL, USER_AGENT, PoliteClient, update_catalog
from beamng_catalog.parse import listing_page_ok, parse_listing_page, parse_resource_page
from beamng_catalog.robots import parse_robots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish the BeamNG mod catalog.")
    commands = parser.add_subparsers(dest="command", required=True)

    update = commands.add_parser("update", help="Crawl beamng.com and write the catalog.")
    update.add_argument("--catalog-dir", required=True)
    update.add_argument("--seed", required=True)
    update.add_argument("--mode", choices=("incremental", "full"), required=True)
    update.add_argument("--max-details", type=int, default=None)
    update.add_argument("--max-seconds", type=float, default=None)

    seed = commands.add_parser("publish-seed", help="Write the seed catalog without crawling.")
    seed.add_argument("--catalog-dir", required=True)
    seed.add_argument("--seed", required=True)

    commands.add_parser("verify-live", help="Parse a few live pages and print what was found.")

    args = parser.parse_args(argv)
    if args.command == "publish-seed":
        publish_seed(Path(args.catalog_dir), Path(args.seed))
        print(f"catalog: published seed into {args.catalog_dir}")
        return 0
    if args.command == "verify-live":
        return verify_live()
    return update_catalog(
        Path(args.catalog_dir),
        Path(args.seed),
        args.mode,
        max_seconds=args.max_seconds,
        max_details=args.max_details,
    )


def verify_live() -> int:
    client = PoliteClient()
    print(f"catalog: user-agent {USER_AGENT}")
    robots = parse_robots(client.get(ROBOTS_URL))
    print(f"catalog: robots disallow={robots.disallow} delay={robots.delay}")
    if not robots.allows("/resources/"):
        print("catalog: robots.txt disallows /resources/")
        return 1
    listing_url = "https://www.beamng.com/resources/categories/land.3/?order=last_update"
    listing_html = client.get(listing_url)
    if not listing_page_ok(listing_html):
        print("catalog: live listing page was not recognized")
        return 1
    listing = parse_listing_page(listing_html, page_category_id=3, page_category_title="Land")
    print(f"catalog: land page has {len(listing['items'])} mods, last page {listing['last_page']}")
    if not listing["items"] or listing["items"][0].get("forum_id") is None:
        print("catalog: live listing parser returned no mods")
        return 1
    first = listing["items"][0]
    print(f"catalog: first listing item {first['forum_id']} {first['title']} version={first['version']}")
    checked = 0
    for slug, forum_id, expect_tag in (
        ("tyrelabs", 39641, "M2YNFTLV4"),
        ("polish-roads", 5846, "MN2D9XPFH"),
    ):
        detail = parse_resource_page(client.get(f"https://www.beamng.com/resources/{slug}.{forum_id}/"))
        print(
            "catalog: live",
            slug,
            "tagid",
            detail["tagid"],
            "version",
            detail["version"],
            "first_release",
            detail["first_release"],
            "screenshots",
            len(detail["screenshots"]),
            "thread",
            detail["forum_thread"],
            "mentions",
            detail["mentions_versions"],
            "requires",
            detail["requires"],
            "tags",
            detail["tags"],
        )
        if detail["tagid"] != expect_tag or not detail["version"]:
            print(f"catalog: unexpected live parse for {slug}")
            return 1
        checked += 1
    if checked != 2:
        return 1
    print("catalog: live parsers matched the expected resource ids")
    return 0


if __name__ == "__main__":
    sys.exit(main())
