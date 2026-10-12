# BeamNG mod catalog

A free, scheduled catalog of public [BeamNG.drive](https://www.beamng.com/resources/) repository mods. An in-game marketplace can download this catalog instead of each player crawling the site.

The code lives on `main`. The files the game should fetch live on the `catalog` branch.

## URLs

Prefer the gzip file. It is the same JSON document, compressed.

| File | URL |
| --- | --- |
| Catalog (gzip) | `https://raw.githubusercontent.com/TannorApps/beamng-marketplace-catalog/catalog/catalog.json.gz` |
| Catalog | `https://raw.githubusercontent.com/TannorApps/beamng-marketplace-catalog/catalog/catalog.json` |
| Schema | `https://raw.githubusercontent.com/TannorApps/beamng-marketplace-catalog/catalog/meta.json` |
| Trending | `https://raw.githubusercontent.com/TannorApps/beamng-marketplace-catalog/catalog/trending.json` |
| Daily snapshot | `https://raw.githubusercontent.com/TannorApps/beamng-marketplace-catalog/catalog/snapshots/YYYY-MM-DD.json` |

`raw.githubusercontent.com` may cache a response for a few minutes. The day-one catalog is the seeded list of 8,611 mods. Later runs update it in place.

## Document shape

`catalog.json` is `{version, generated, count, source, mods}`. `generated` is a Unix timestamp. `source` is `seed` until a crawl succeeds, then `crawl`.

Each mod always has:

`tagid`, `title`, `prefix_title`, `tag_line`, `username`, `cats`, `category_title`, `last_update`, `resource_date`, `download_count`, `rating_avg`, `rating_count`, `filesize`, `filename`, `path`

`path` is `tagid/<repository version id>/`, for example `M2YNFTLV4/73278/`. `download_count` is the current version's download count. `filesize` stays the exact byte size when the page only shows the same rounded label such as `1.3 MB`.

Fields added when a resource page has been read:

| Field | Meaning |
| --- | --- |
| `thumb` | Absolute resource-icon URL |
| `url` | `https://www.beamng.com/resources/<slug>.<id>/` |
| `resource_id` | The `<id>` in that URL. `requires` uses this id. It is not the version id inside `path`. |
| `first_release` | Unix time of the first release |
| `version` | The mod's own version label, such as `1.0` or `3.3` |
| `screenshots` | Absolute image URLs from the current description |
| `forum_thread` | Discussion thread URL, or `null` if the resource has none |
| `mentions_versions` | Game versions mentioned in the description. `0.39` and `0.39.4` are both stored as `0.39` |
| `requires` | Other resource ids linked within 120 characters of require, requires, required, needed, dependency, needs, must have, or install also |
| `requires_tagid` | Same order as `requires`. The dependency's `tagid` when that mod is already in the catalog, otherwise `null` |
| `tags` | Auto keywords: `brand:<name>`, `vehicle:<type>`, `map`, `pack` |

`meta.json` is `{generated, count, schema}` and lists the same fields, including the brand and vehicle-type vocabulary. Absent optional fields mean that mod has not been opened yet. Empty lists mean the page was read and nothing matched.

Categories: 3 Land, 4 Air, 5 Props, 6 Boats, 7 Mods of Mods, 8 Scenarios, 9 Terrains, Levels, Maps, 10 User Interface Apps, 12 Skins, 13 Sounds, 14 Configurations, 15 License Plates.

## Trending and snapshots

`snapshots/YYYY-MM-DD.json` is `{date, totals}` where `totals` maps `tagid` to that day's `download_count`. Files older than 400 days are deleted.

`trending.json` has `periods.day`, `week`, `month`, `year`, and `all_time`. Each period has `estimated`, `label`, and up to 200 `items` with `tagid`, `title`, `username`, `category_title`, `download_count`, `delta`, and `estimated`.

- `measured` — a snapshot covers that window
- `estimated: extrapolated from shorter history` — the observed daily rate is scaled up
- `estimated: scaled from a longer gap` — the only older snapshot spans more than the window
- `estimated: not enough history` — `delta` is `null` and the list is ordered by total downloads
- `measured: all-time download total` — `delta` is the current `download_count`

## Updates

GitHub Actions uses a GitHub-hosted runner and the built-in token. There are no stored secrets and no paid services.

- Every 6 hours: re-read the latest-updated pages of each category, then refresh a limited batch of resource pages that are new, updated, or not yet opened.
- Mondays: walk every category page, add mods, and drop mods that are no longer listed. A drop happens only after that walk finishes and every listed resource has been checked. Losing more than half the catalog in one run is rejected.
- `workflow_dispatch` accepts `incremental` or `full`.

If the site cannot be reached, or `robots.txt` disallows `/resources/`, the job leaves the last good catalog in place.

Requests use a descriptive User-Agent, stay at about one per second (or `Crawl-delay`, whichever is slower), and back off on HTTP 429 and 5xx. The current `robots.txt` allows the resource pages and disallows `/library`. The site terms describe personal, non-commercial use of beamng.com and do not mention crawling; the forum rules do not either. This crawler is deliberately slow so players do not each hit the site.

## Tests

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Parser tests use saved HTML fixtures. `python -m beamng_catalog verify-live` checks a listing page and two resource pages against the live site.
