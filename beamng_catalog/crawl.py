"""Polite crawler for the public BeamNG resource catalog.

One request at a time, with backoff. A failed run leaves the last published
catalog on disk. Mods are removed only after a full category sweep finishes
and every listed resource has been checked.
"""

from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import requests

from beamng_catalog.categories import CATEGORIES, category_page_url, resource_page_url
from beamng_catalog.catalog import (
    Index,
    apply_listing,
    load_catalog,
    upsert_detail,
    load_state,
    publication_ok,
    resolve_requires,
    write_outputs,
)
from beamng_catalog.parse import listing_page_ok, parse_listing_page, parse_resource_page
from beamng_catalog.robots import parse_robots

USER_AGENT = (
    "beamng-marketplace-catalog/1.0 "
    "(+https://github.com/TannorApps/beamng-marketplace-catalog; "
    "polite catalog mirror; about 1 request/second)"
)
ROBOTS_URL = "https://www.beamng.com/robots.txt"
ALLOWED_HOSTS = {"www.beamng.com", "beamng.com"}
OVERLAP_SECONDS = 48 * 60 * 60
INCREMENTAL_PAGE_CAP = 8
INCREMENTAL_DETAIL_BUDGET = 400
BACKGROUND_DETAILS = 200


class CrawlError(Exception):
    pass


class NotFound(CrawlError):
    pass


class PoliteClient:
    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en",
            }
        )
        self._last = 0.0

    def get(self, url: str) -> str:
        host = urlparse(url).hostname or ""
        if host not in ALLOWED_HOSTS:
            raise CrawlError(f"refusing non-beamng host {host}")
        error: Exception | None = None
        for attempt in range(5):
            self._wait(0 if attempt == 0 else min(60.0, self.interval * (2**attempt)))
            try:
                response = self.session.get(url, timeout=45)
            except requests.RequestException as exc:
                error = exc
                continue
            if response.status_code == 200:
                return response.text
            if response.status_code == 404:
                raise NotFound(url)
            if response.status_code in {429, 500, 502, 503, 504}:
                error = CrawlError(f"HTTP {response.status_code} for {url}")
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    time.sleep(min(120, int(retry_after)))
                continue
            raise CrawlError(f"HTTP {response.status_code} for {url}")
        raise CrawlError(f"failed to fetch {url}: {error}")

    def _wait(self, extra: float) -> None:
        now = time.monotonic()
        delay = max(0.0, self.interval - (now - self._last)) + max(0.0, extra)
        if delay:
            time.sleep(delay)
        self._last = time.monotonic()


def update_catalog(
    catalog_dir,
    seed_path,
    mode: str,
    *,
    now: int | None = None,
    max_seconds: float | None = None,
    max_details: int | None = None,
    categories=None,
    client=None,
) -> int:
    if mode not in {"incremental", "full"}:
        raise ValueError(f"unknown mode {mode}")
    catalog_dir = _path(catalog_dir)
    seed = _path(seed_path) if seed_path else None
    moment = int(now if now is not None else time.time())
    if max_seconds is None:
        max_seconds = float(os.environ.get("CATALOG_MAX_SECONDS", "16200"))
    deadline = time.monotonic() + max_seconds
    categories = list(categories or CATEGORIES)
    http = client or PoliteClient()
    pages_ok = 0
    advance_watermark = False

    def timed_out() -> bool:
        return time.monotonic() >= deadline

    try:
        robots_text = http.get(ROBOTS_URL)
        robots = parse_robots(robots_text)
    except Exception as exc:
        print(f"catalog: could not read robots.txt ({exc}); leaving the catalog unchanged")
        return 1
    if not robots.allows("/resources/") or not robots.allows("/resources/categories/"):
        print("catalog: robots.txt disallows the resource pages; leaving the catalog unchanged")
        return 1
    if robots.delay:
        http.interval = max(1.0, float(robots.delay))
    print(f"catalog: robots ok, interval {http.interval:.1f}s, mode {mode}")

    try:
        catalog = load_catalog(catalog_dir, seed)
    except FileNotFoundError as exc:
        print(f"catalog: {exc}")
        return 1
    mods = catalog.get("mods")
    if not isinstance(mods, list) or not mods:
        print("catalog: existing catalog has no mods; leaving it unchanged")
        return 1
    old_count = len(mods)
    state = load_state(catalog_dir)
    index = Index(mods)
    queue: list[int] = [int(item) for item in state.get("detail_queue") or []]
    queued = set(queue)

    def enqueue(forum_id: int) -> None:
        if forum_id not in queued:
            queue.append(forum_id)
            queued.add(forum_id)

    def note(item: dict, sweep_seen: set[int] | None) -> None:
        forum_id = int(item["forum_id"])
        entry = state["by_forum"].setdefault(str(forum_id), {})
        if item.get("slug"):
            entry["slug"] = item["slug"]
        tagid = entry.get("tagid")
        if tagid and tagid in index.by_tag:
            apply_listing(index.by_tag[tagid], item)
        needs = (
            not entry.get("tagid")
            or not entry.get("detailed")
            or (item.get("last_update") and entry.get("last_update") != item["last_update"])
        )
        if needs:
            enqueue(forum_id)
        if sweep_seen is not None and forum_id not in sweep_seen:
            sweep_seen.add(forum_id)

    try:
        if mode == "incremental":
            recent_pages, recent_done = _walk_recent(
                http,
                categories,
                catalog,
                state,
                note,
                timed_out,
            )
            pages_ok += recent_pages
            advance_watermark = recent_done
        if mode == "full" or state.get("sweep"):
            pages_ok += _walk_sweep(
                http,
                categories,
                state,
                note,
                timed_out,
                start_new=(mode == "full" and not _sweep_active(state)),
            )
        elif mode == "incremental":
            _queue_background(state, enqueue, BACKGROUND_DETAILS)
        detail_budget = max_details
        if detail_budget is None and mode == "incremental":
            detail_budget = INCREMENTAL_DETAIL_BUDGET
        pages_ok += _drain_details(
            http,
            index,
            state,
            queue,
            queued,
            moment,
            timed_out,
            detail_budget,
        )
    except CrawlError as exc:
        print(f"catalog: crawl stopped: {exc}")
        if pages_ok == 0:
            print("catalog: no page was read; leaving the catalog unchanged")
            return 1
        print("catalog: saving partial updates and not deleting anything")
        allow_shrink = False
        advance_watermark = False
    else:
        allow_shrink = _maybe_finish_sweep(state, index, queue, moment)

    state["detail_queue"] = queue
    resolve_requires(index.mods, state["by_forum"])
    new_count = len(index.mods)
    ok, reason = publication_ok(old_count, new_count, allow_shrink)
    if not ok:
        print(f"catalog: {reason}; leaving the catalog unchanged")
        return 1
    if advance_watermark:
        state["last_incremental_success"] = moment
    catalog["generated"] = moment
    catalog["count"] = new_count
    catalog["source"] = "crawl"
    catalog["version"] = 1
    write_outputs(catalog_dir, catalog, state, moment)
    print(f"catalog: wrote {new_count} mods (was {old_count}), shrink={allow_shrink}")
    return 0


def _sweep_active(state: dict) -> bool:
    sweep = state.get("sweep")
    return bool(sweep) and not sweep.get("listings_done")


def _walk_recent(http, categories, catalog, state, note, timed_out) -> tuple[int, bool]:
    watermark = state.get("last_incremental_success") or catalog.get("generated") or 0
    pages = 0
    completed = True
    for _cid, slug, title in categories:
        if timed_out():
            completed = False
            break
        last_page = None
        page = 1
        while last_page is None or page <= last_page:
            if timed_out() or page > INCREMENTAL_PAGE_CAP:
                completed = False
                break
            html = http.get(category_page_url(slug, _cid, page))
            if not listing_page_ok(html):
                raise CrawlError(f"category {title} page {page} was not a resource listing")
            parsed = parse_listing_page(html, page_category_id=_cid, page_category_title=title)
            pages += 1
            if last_page is None:
                last_page = parsed["last_page"]
            for item in parsed["items"]:
                note(item, None)
            print(f"catalog: incremental {title} page {page}/{last_page} ({len(parsed['items'])} mods)")
            times = [item["last_update"] for item in parsed["items"] if item.get("last_update")]
            if times and min(times) < int(watermark) - OVERLAP_SECONDS:
                break
            page += 1
        if not completed:
            break
    return pages, completed


def _walk_sweep(http, categories, state, note, timed_out, start_new: bool) -> int:
    if start_new or not state.get("sweep"):
        state["sweep"] = {"cat_index": 0, "page": 1, "seen": [], "listings_done": False}
    sweep = state["sweep"]
    if sweep.get("listings_done"):
        return 0
    seen = set(int(item) for item in sweep.get("seen") or [])
    pages = 0
    cat_index = int(sweep.get("cat_index") or 0)
    page = int(sweep.get("page") or 1)
    while cat_index < len(categories):
        cid, slug, title = categories[cat_index]
        last_page = None
        while True:
            if timed_out():
                sweep["cat_index"] = cat_index
                sweep["page"] = page
                sweep["seen"] = sorted(seen)
                print("catalog: full sweep paused at the time budget")
                return pages
            html = http.get(category_page_url(slug, cid, page))
            if not listing_page_ok(html):
                sweep["cat_index"] = cat_index
                sweep["page"] = page
                sweep["seen"] = sorted(seen)
                raise CrawlError(f"category {title} page {page} was not a resource listing")
            parsed = parse_listing_page(html, page_category_id=cid, page_category_title=title)
            pages += 1
            if last_page is None:
                last_page = parsed["last_page"]
            for item in parsed["items"]:
                note(item, seen)
            print(f"catalog: full {title} page {page}/{last_page} ({len(parsed['items'])} mods)")
            page += 1
            if page > last_page:
                break
        cat_index += 1
        page = 1
    sweep["cat_index"] = cat_index
    sweep["page"] = page
    sweep["seen"] = sorted(seen)
    sweep["listings_done"] = True
    print(f"catalog: full sweep listings finished, {len(seen)} resources seen")
    return pages


def _queue_background(state: dict, enqueue, limit: int) -> None:
    ranked = []
    for key, entry in state["by_forum"].items():
        if not entry or entry.get("missing") or not entry.get("slug"):
            continue
        try:
            forum_id = int(key)
        except ValueError:
            continue
        rank = 0 if not entry.get("detailed") else 1
        ranked.append((rank, int(entry.get("checked_at") or 0), forum_id))
    ranked.sort()
    for _rank, _checked, forum_id in ranked[:limit]:
        enqueue(forum_id)


def _drain_details(http, index, state, queue, queued, moment, timed_out, budget) -> int:
    done = 0
    while queue:
        if timed_out():
            print("catalog: detail fetches paused at the time budget")
            break
        if budget is not None and done >= budget:
            break
        forum_id = queue.pop(0)
        queued.discard(forum_id)
        entry = state["by_forum"].setdefault(str(forum_id), {})
        slug = entry.get("slug") or ""
        url = resource_page_url(slug, forum_id) if slug else f"https://www.beamng.com/resources/{forum_id}/"
        try:
            html = http.get(url)
        except NotFound:
            entry["missing"] = True
            entry["detailed"] = True
            entry["checked_at"] = moment
            print(f"catalog: resource {forum_id} is gone")
            continue
        except CrawlError:
            queue.insert(0, forum_id)
            queued.add(forum_id)
            raise
        try:
            detail = parse_resource_page(html)
        except Exception as exc:
            queue.insert(0, forum_id)
            queued.add(forum_id)
            raise CrawlError(f"could not parse resource {forum_id}: {exc}") from exc
        if not detail.get("forum_id"):
            detail["forum_id"] = forum_id
        if not detail.get("tagid"):
            if detail.get("has_unique_id_label"):
                entry["failures"] = int(entry.get("failures") or 0) + 1
                entry["detailed"] = False
                entry["checked_at"] = moment
                print(f"catalog: resource {forum_id} had an unreadable unique id")
                continue
            entry["no_repo"] = True
            entry["detailed"] = True
            entry["checked_at"] = moment
            continue
        mod = upsert_detail(index, detail)
        entry.update(
            {
                "tagid": (mod or {}).get("tagid") or detail.get("tagid"),
                "version_id": detail.get("version_id"),
                "last_update": detail.get("last_update"),
                "slug": detail.get("slug") or slug,
                "checked_at": moment,
                "detailed": True,
                "missing": False,
                "no_repo": False,
            }
        )
        done += 1
        if done % 25 == 0:
            print(f"catalog: fetched {done} resource pages, {len(queue)} queued")
    return done


def _maybe_finish_sweep(state, index, queue, moment) -> bool:
    sweep = state.get("sweep")
    if not sweep or not sweep.get("listings_done") or queue:
        return False
    seen_tagids = set()
    unresolved = 0
    for forum_id in sweep.get("seen") or []:
        entry = state["by_forum"].get(str(forum_id)) or {}
        if entry.get("missing") or entry.get("no_repo"):
            continue
        tagid = entry.get("tagid")
        if tagid:
            seen_tagids.add(tagid)
            continue
        unresolved += 1
    if unresolved:
        print(f"catalog: {unresolved} listed resources are still unresolved; not dropping mods")
        return False
    before = len(index.mods)
    kept = [mod for mod in index.mods if mod.get("tagid") in seen_tagids]
    removed = before - len(kept)
    if removed:
        index.mods[:] = kept
        print(f"catalog: full sweep dropped {removed} mods that are no longer listed")
    state["sweep"] = None
    state["last_full_success"] = moment
    return True


def _path(value):
    from pathlib import Path

    return value if isinstance(value, Path) else Path(value)
