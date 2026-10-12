"""Catalog documents, merging, snapshots, and trending."""

from __future__ import annotations

import gzip
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from beamng_catalog.parse import (
    choose_filesize,
    detect_tags,
    path_version_id,
    schema_document,
)

SNAPSHOT_KEEP_DAYS = 400
TRENDING_LIMIT = 200


def dump_catalog(catalog: dict) -> bytes:
    text = json.dumps(catalog, ensure_ascii=True, separators=(",", ":"))
    return text.encode("utf-8")


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_seed(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def load_catalog(directory: Path, seed_path: Path | None) -> dict:
    catalog_path = directory / "catalog.json"
    if catalog_path.exists():
        return load_json(catalog_path)
    if seed_path is not None and seed_path.exists():
        return load_seed(seed_path)
    raise FileNotFoundError(f"no catalog in {directory} and no seed at {seed_path}")


def load_state(directory: Path) -> dict:
    path = directory / "state.json"
    if path.exists():
        state = load_json(path)
    else:
        state = {}
    state.setdefault("version", 1)
    state.setdefault("by_forum", {})
    state.setdefault("detail_queue", [])
    state.setdefault("sweep", None)
    state.setdefault("last_incremental_success", None)
    state.setdefault("last_full_success", None)
    return state


class Index:
    def __init__(self, mods: list[dict]):
        self.mods = mods
        self.by_tag: dict[str, dict] = {}
        self.by_version: dict[int, dict] = {}
        for mod in mods:
            self.remember(mod)

    def remember(self, mod: dict) -> None:
        tagid = mod.get("tagid")
        if tagid:
            self.by_tag[tagid] = mod
        version_id = path_version_id(mod.get("path"))
        if version_id is not None:
            self.by_version[version_id] = mod


def apply_listing(mod: dict, item: dict) -> None:
    for key in ("title", "tag_line", "username", "category_title", "url", "thumb"):
        if item.get(key):
            mod[key] = item[key]
    if "prefix_title" in item:
        mod["prefix_title"] = item.get("prefix_title") or ""
    if item.get("cats"):
        mod["cats"] = list(item["cats"])
    if item.get("last_update"):
        mod["last_update"] = item["last_update"]
    if item.get("resource_date"):
        mod["resource_date"] = item["resource_date"]
    if item.get("rating_avg") is not None:
        mod["rating_avg"] = item["rating_avg"]
    if item.get("rating_count") is not None:
        mod["rating_count"] = item["rating_count"]
    if item.get("version") and not mod.get("version"):
        mod["version"] = item["version"]
    # Listing text is a preview. A description scan (screenshots key) is kept.
    if "screenshots" not in mod:
        mod["tags"] = detect_tags(
            title=mod.get("title") or "",
            tag_line=mod.get("tag_line") or "",
            category_title=mod.get("category_title") or "",
            category_ids=mod.get("cats") or [],
        )


def upsert_detail(index: Index, detail: dict) -> dict | None:
    """Insert or update a mod from a parsed resource page.

    Match an existing row on tagid, then on the repository version id in path.
    """
    tagid = (detail.get("tagid") or "").strip()
    version_id = detail.get("version_id")
    existing = index.by_tag.get(tagid) if tagid else None
    if existing is None and version_id is not None:
        existing = index.by_version.get(version_id)
    if existing is None:
        if not tagid or not version_id:
            return None
        existing = _new_mod(tagid, version_id)
        index.mods.append(existing)
    previous_version = path_version_id(existing.get("path"))
    previous_tag = existing.get("tagid")
    _fill_detail(existing, detail, version_id)
    if previous_tag and previous_tag != existing.get("tagid") and index.by_tag.get(previous_tag) is existing:
        del index.by_tag[previous_tag]
    current_version = path_version_id(existing.get("path"))
    if (
        previous_version
        and previous_version != current_version
        and index.by_version.get(previous_version) is existing
    ):
        del index.by_version[previous_version]
    index.remember(existing)
    return existing


def _new_mod(tagid: str, version_id: int) -> dict:
    return {
        "tagid": tagid,
        "title": "",
        "prefix_title": "",
        "tag_line": "",
        "username": "",
        "cats": [],
        "category_title": "",
        "last_update": 0,
        "resource_date": 0,
        "download_count": 0,
        "rating_avg": 0,
        "rating_count": 0,
        "filesize": 0,
        "filename": "",
        "path": f"{tagid}/{version_id}/",
    }


def _fill_detail(mod: dict, detail: dict, version_id: int | None) -> None:
    if detail.get("tagid"):
        mod["tagid"] = detail["tagid"]
    tagid = mod.get("tagid") or ""
    if tagid and version_id:
        previous = path_version_id(mod.get("path"))
        mod["path"] = f"{tagid}/{version_id}/"
        if previous and previous != version_id:
            # remember() replaces the version index; callers drop the old key.
            pass
    for key in ("title", "tag_line", "username", "category_title", "url", "thumb"):
        if detail.get(key):
            mod[key] = detail[key]
    if "prefix_title" in detail:
        mod["prefix_title"] = detail.get("prefix_title") or ""
    if detail.get("cats"):
        mod["cats"] = list(detail["cats"])
    if detail.get("last_update"):
        mod["last_update"] = detail["last_update"]
    if detail.get("resource_date"):
        mod["resource_date"] = detail["resource_date"]
    if detail.get("first_release"):
        mod["first_release"] = detail["first_release"]
    if detail.get("download_count") is not None:
        mod["download_count"] = int(detail["download_count"])
    if detail.get("rating_avg") is not None:
        mod["rating_avg"] = detail["rating_avg"]
    if detail.get("rating_count") is not None:
        mod["rating_count"] = detail["rating_count"]
    if detail.get("version"):
        mod["version"] = detail["version"]
    chosen = choose_filesize(mod.get("filesize"), detail.get("filesize_label"))
    if chosen is not None:
        mod["filesize"] = int(chosen)
    if detail.get("filename"):
        mod["filename"] = detail["filename"]
    if detail.get("forum_id"):
        mod["resource_id"] = int(detail["forum_id"])
    mod["screenshots"] = list(detail.get("screenshots") or [])
    mod["forum_thread"] = detail.get("forum_thread")
    mod["mentions_versions"] = list(detail.get("mentions_versions") or [])
    mod["requires"] = list(detail.get("requires") or [])
    mod["tags"] = list(detail.get("tags") or [])


def resolve_requires(mods: list[dict], by_forum: dict) -> None:
    forum_to_tag: dict[int, str] = {}
    for key, entry in (by_forum or {}).items():
        tagid = (entry or {}).get("tagid")
        if not tagid:
            continue
        try:
            forum_to_tag[int(key)] = tagid
        except (TypeError, ValueError):
            continue
    for mod in mods:
        resource_id = mod.get("resource_id")
        tagid = mod.get("tagid")
        if resource_id and tagid:
            try:
                forum_to_tag[int(resource_id)] = tagid
            except (TypeError, ValueError):
                pass
    for mod in mods:
        requires = mod.get("requires")
        if requires is None:
            continue
        resolved = []
        for resource_id in requires:
            try:
                resolved.append(forum_to_tag.get(int(resource_id)))
            except (TypeError, ValueError):
                resolved.append(None)
        mod["requires_tagid"] = resolved


def publication_ok(old_count: int, new_count: int, allow_shrink: bool) -> tuple[bool, str]:
    if new_count <= 0:
        return False, "refusing to publish an empty catalog"
    if old_count and not allow_shrink and new_count < old_count:
        return False, "refusing to shrink the catalog without a completed full sweep"
    if old_count and allow_shrink and new_count * 2 < old_count:
        return False, "refusing to drop more than half the catalog in one sweep"
    return True, ""


def snapshot_day(unix: int) -> str:
    return datetime.fromtimestamp(unix, timezone.utc).date().isoformat()


def write_snapshot(directory: Path, mods: list[dict], unix: int) -> Path:
    day = snapshot_day(unix)
    totals = {}
    for mod in mods:
        tagid = mod.get("tagid")
        if not tagid:
            continue
        totals[tagid] = int(mod.get("download_count") or 0)
    payload = {"date": day, "totals": totals}
    folder = directory / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.json"
    _atomic_write(path, json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return path


def prune_snapshots(directory: Path, today: date, keep_days: int = SNAPSHOT_KEEP_DAYS) -> list[Path]:
    folder = directory / "snapshots"
    if not folder.exists():
        return []
    cutoff = today - timedelta(days=keep_days)
    removed = []
    for path in folder.glob("*.json"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
            continue
        try:
            stamped = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if stamped < cutoff:
            path.unlink()
            removed.append(path)
    return removed


def load_snapshots(directory: Path) -> list[tuple[date, dict]]:
    folder = directory / "snapshots"
    if not folder.exists():
        return []
    found = []
    for path in folder.glob("*.json"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
            continue
        data = load_json(path)
        raw_day = data.get("date") or path.stem
        try:
            stamped = date.fromisoformat(raw_day)
        except ValueError:
            continue
        found.append((stamped, data.get("totals") or {}))
    found.sort(key=lambda item: item[0])
    return found


def build_trending(mods: list[dict], snapshots: list[tuple[date, dict]], generated_unix: int) -> dict:
    today = datetime.fromtimestamp(generated_unix, timezone.utc).date()
    periods = {
        "all_time": _all_time(mods),
    }
    for name, days in (("day", 1), ("week", 7), ("month", 30), ("year", 365)):
        periods[name] = _period(mods, snapshots, today, days)
    return {"generated": generated_unix, "periods": periods}


def _row(mod: dict, delta, estimated: bool) -> dict:
    return {
        "tagid": mod.get("tagid") or "",
        "title": mod.get("title") or "",
        "username": mod.get("username") or "",
        "category_title": mod.get("category_title") or "",
        "download_count": int(mod.get("download_count") or 0),
        "delta": delta,
        "estimated": estimated,
    }


def _top(rows: list[dict]) -> list[dict]:
    def sort_key(row: dict):
        delta = row["delta"]
        missing = delta is None
        return (missing, -(delta or 0), -row["download_count"], row["tagid"])

    return sorted(rows, key=sort_key)[:TRENDING_LIMIT]


def _all_time(mods: list[dict]) -> dict:
    rows = [_row(mod, int(mod.get("download_count") or 0), False) for mod in mods]
    return {
        "days": None,
        "estimated": False,
        "label": "measured: all-time download total",
        "items": _top(rows),
    }


def _period(mods: list[dict], snapshots: list[tuple[date, dict]], today: date, days: int) -> dict:
    target = today - timedelta(days=days)
    older = [snap for snap in snapshots if snap[0] <= target]
    if older:
        base_date, base_totals = older[-1]
        span = max((today - base_date).days, 1)
        close = (today - base_date).days <= days + 1
        rows = []
        for mod in mods:
            tagid = mod.get("tagid")
            current = int(mod.get("download_count") or 0)
            if tagid in base_totals:
                raw = current - int(base_totals[tagid])
                if close:
                    rows.append(_row(mod, raw, False))
                else:
                    rows.append(_row(mod, int(round(raw * days / span)), True))
            else:
                rows.append(_row(mod, current, True))
        return {
            "days": days,
            "estimated": not close,
            "label": "measured" if close else "estimated: scaled from a longer gap",
            "items": _top(rows),
        }
    if len(snapshots) >= 2:
        oldest_date, oldest_totals = snapshots[0]
        newest_date, _newest_totals = snapshots[-1]
        span = (newest_date - oldest_date).days
        if span >= 1:
            rows = []
            for mod in mods:
                tagid = mod.get("tagid")
                current = int(mod.get("download_count") or 0)
                if tagid in oldest_totals:
                    raw = current - int(oldest_totals[tagid])
                else:
                    raw = current
                rows.append(_row(mod, int(round(raw * days / span)), True))
            return {
                "days": days,
                "estimated": True,
                "label": "estimated: extrapolated from shorter history",
                "items": _top(rows),
            }
    rows = [_row(mod, None, True) for mod in mods]
    return {
        "days": days,
        "estimated": True,
        "label": "estimated: not enough history",
        "items": _top(rows),
    }


def meta_document(catalog: dict) -> dict:
    return {
        "generated": catalog.get("generated"),
        "count": catalog.get("count"),
        "schema": schema_document(),
    }


def write_outputs(directory: Path, catalog: dict, state: dict | None, unix: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    catalog["count"] = len(catalog.get("mods") or [])
    body = dump_catalog(catalog)
    _atomic_write(directory / "catalog.json", body)
    _atomic_write(directory / "catalog.json.gz", gzip.compress(body, mtime=0))
    meta = meta_document(catalog)
    _atomic_write(
        directory / "meta.json",
        json.dumps(meta, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8") + b"\n",
    )
    write_snapshot(directory, catalog["mods"], unix)
    today = datetime.fromtimestamp(unix, timezone.utc).date()
    prune_snapshots(directory, today)
    trending = build_trending(catalog["mods"], load_snapshots(directory), unix)
    _atomic_write(
        directory / "trending.json",
        json.dumps(trending, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
    )
    if state is not None:
        _atomic_write(
            directory / "state.json",
            json.dumps(state, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        )


def publish_seed(directory: Path, seed_path: Path) -> dict:
    if (directory / "catalog.json").exists():
        raise FileExistsError(f"{directory / 'catalog.json'} already exists")
    catalog = load_seed(seed_path)
    raw = gzip.open(seed_path, "rb").read()
    dumped = dump_catalog(catalog)
    if dumped != raw:
        raise RuntimeError("seed catalog did not round-trip; refusing to rewrite it")
    unix = int(catalog.get("generated") or 0)
    state = load_state(directory)
    write_outputs(directory, catalog, state, unix)
    # write_outputs re-dumps catalog.json. It must stay byte-identical to the seed.
    written = (directory / "catalog.json").read_bytes()
    if written != raw:
        raise RuntimeError("published catalog.json does not match the seed bytes")
    return catalog


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
