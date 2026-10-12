"""HTML parsers for the public BeamNG resource pages.

The parsers are pure: they do not fetch anything. Listing pages and resource
pages use the markup served by beamng.com (XenForo resource manager).
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, NavigableString, Tag

BASE = "https://www.beamng.com/"
# Guest-facing timestamps on the site match Europe/Berlin. data-time is preferred.
BERLIN = ZoneInfo("Europe/Berlin")

BRANDS = (
    "autobello",
    "bruckell",
    "burnside",
    "cherrier",
    "civetta",
    "etk",
    "gavril",
    "hirochi",
    "ibishu",
    "soliad",
    "wentward",
)
# Longer phrases first so "motorcycle" wins the search, not a shorter token.
VEHICLE_TYPES = (
    "airplane",
    "aircraft",
    "helicopter",
    "motorcycle",
    "motorbike",
    "forklift",
    "tractor",
    "ambulance",
    "pickup",
    "scooter",
    "trailer",
    "buggy",
    "truck",
    "train",
    "plane",
    "boat",
    "bike",
    "suv",
    "van",
    "bus",
    "atv",
    "utv",
    "car",
    "semi",
)

GAME_VERSION_RE = re.compile(r"(?<![\d.])0\.3\d(?:\.\d+)*(?!\d)")
DEPENDENCY_RE = re.compile(
    r"\b(?:required|requires|require|dependencies|dependency|needed|needs|must\s+have|install\s+also)\b",
    re.I,
)
RESOURCE_HREF_RE = re.compile(r"(?:^|/)resources/([^/?#]+)\.(\d+)/?$")
DEPENDENCY_WINDOW = 120

CORE_FIELDS = [
    "tagid",
    "title",
    "prefix_title",
    "tag_line",
    "username",
    "cats",
    "category_title",
    "last_update",
    "resource_date",
    "download_count",
    "rating_avg",
    "rating_count",
    "filesize",
    "filename",
    "path",
]
OPTIONAL_FIELDS = [
    "thumb",
    "url",
    "resource_id",
    "first_release",
    "version",
    "screenshots",
    "forum_thread",
    "mentions_versions",
    "requires",
    "requires_tagid",
    "tags",
]


def schema_document() -> dict:
    return {
        "version": 1,
        "required": list(CORE_FIELDS),
        "optional": list(OPTIONAL_FIELDS),
        "resource_id": (
            "Public id from /resources/<slug>.<id>/. "
            "requires uses this same id. The trailing number in path "
            "(tagid/<versionId>/) is the repository version id and is only "
            "used to match older rows."
        ),
        "first_release": "Unix seconds of the resource's first release.",
        "version": "The mod's own version label, not the catalog schema version.",
        "screenshots": "Absolute image URLs from the current description.",
        "forum_thread": "Absolute discussion-thread URL, or null when the resource has none.",
        "mentions_versions": (
            "Game versions mentioned in the description. "
            "A mention like 0.39 or 0.39.4 is stored as 0.39."
        ),
        "requires": (
            "Other resource ids linked within 120 characters of "
            "require, requires, required, needed, dependency, needs, "
            "must have, or install also."
        ),
        "requires_tagid": (
            "Parallel to requires. The tagid when that resource id is already "
            "in the catalog, otherwise null."
        ),
        "tags": "Auto keywords: brand:<name>, vehicle:<type>, map, pack.",
        "tag_vocabulary": {
            "brands": list(BRANDS),
            "vehicle_types": list(VEHICLE_TYPES),
            "map": "Category Terrains, or map/terrain in the title, tag line, or category title.",
            "pack": "pack, bundle, or collection in the title, tag line, or category title.",
        },
    }


def absolute_url(href: str | None) -> str:
    if not href:
        return ""
    return urljoin(BASE, href)


def parse_number(value) -> int | float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        if "." in text:
            number = float(text)
            if number.is_integer():
                return int(number)
            return number
        return int(text)
    except ValueError:
        return None


def parse_display_datetime(text: str | None) -> int | None:
    if not text:
        return None
    cleaned = " ".join(text.split())
    for fmt in ("%b %d, %Y at %I:%M %p", "%b %d, %Y"):
        try:
            parsed = datetime.strptime(cleaned, fmt).replace(tzinfo=BERLIN)
        except ValueError:
            continue
        return int(parsed.timestamp())
    return None


def parse_time_element(element) -> int | None:
    if element is None:
        return None
    raw = element.get("data-time")
    if raw is not None and str(raw).strip().isdigit():
        return int(str(raw).strip())
    title = element.get("title") or element.get_text(" ", strip=True)
    return parse_display_datetime(title)


def human_size(num: int) -> str:
    """One-decimal binary size, matching the site's '1.3 MB' labels."""
    for name, div in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if num >= div:
            value = (Decimal(num) / Decimal(div)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            return f"{value} {name}"
    return f"{num} B"


def normalize_size_label(label: str | None) -> str | None:
    if not label:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|B)\b", label, re.I)
    if not match:
        return None
    number = float(match.group(1))
    return f"{number:.1f} {match.group(2).upper()}"


def approximate_filesize(label: str | None) -> int | None:
    if not label:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|B)\b", label, re.I)
    if not match:
        return None
    number = float(match.group(1))
    mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}[match.group(2).upper()]
    return int(round(number * mult))


def choose_filesize(previous: int | None, label: str | None) -> int | None:
    """Keep an exact byte size when the page only shows the same rounded label."""
    if not label:
        return previous
    shown = normalize_size_label(label)
    approx = approximate_filesize(label)
    if previous is not None and shown and human_size(int(previous)) == shown:
        return int(previous)
    if approx is not None:
        return approx
    return previous


def path_version_id(path: str | None) -> int | None:
    if not path:
        return None
    match = re.search(r"/(\d+)/?$", path.strip())
    if not match:
        return None
    return int(match.group(1))


def resource_id_from_href(href: str | None) -> int | None:
    """Forum resource id from /resources/<slug>.<id>/, not category or download URLs."""
    if not href:
        return None
    cleaned = href.split("?", 1)[0].split("#", 1)[0].strip()
    match = RESOURCE_HREF_RE.search(cleaned)
    if not match:
        return None
    slug = match.group(1).lower()
    if slug in {"categories", "authors", "reviews", "historyimproved"}:
        return None
    return int(match.group(2))


def listing_page_ok(html: str) -> bool:
    lowered = html.lower()
    if "resourcelistitem" in lowered:
        return True
    return "there are no resources" in lowered or "no resources to display" in lowered


def _rating(scope) -> tuple[int | float | None, int | None]:
    if scope is None:
        return None, None
    number = scope.select_one(".Number")
    hint = scope.select_one(".Hint")
    avg = parse_number(number.get_text(" ", strip=True) if number else None)
    count = None
    if hint:
        match = re.search(r"([\d,]+)\s+ratings?", hint.get_text(" ", strip=True), re.I)
        if match:
            count = int(match.group(1).replace(",", ""))
    return avg, count


def _category_from_href(href: str) -> int | None:
    match = re.search(r"categories/[^/]+\.(\d+)/?", href or "")
    if not match:
        return None
    return int(match.group(1))


def parse_listing_page(
    html: str,
    *,
    page_category_id: int | None = None,
    page_category_title: str | None = None,
) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    last_page = 1
    current_page = 1
    nav = soup.select_one(".PageNav")
    if nav is not None:
        if str(nav.get("data-last") or "").isdigit():
            last_page = int(nav["data-last"])
        if str(nav.get("data-page") or "").isdigit():
            current_page = int(nav["data-page"])
    items = []
    seen: set[int] = set()
    for node in soup.select("li.resourceListItem"):
        item = _parse_listing_item(node, page_category_id, page_category_title)
        if item is None or item["forum_id"] in seen:
            continue
        seen.add(item["forum_id"])
        items.append(item)
    return {"items": items, "last_page": last_page, "current_page": current_page}


def _parse_listing_item(node, page_category_id, page_category_title) -> dict | None:
    raw_id = node.get("id") or ""
    match = re.fullmatch(r"resource-(\d+)", raw_id)
    if not match:
        return None
    forum_id = int(match.group(1))
    title = ""
    slug = ""
    prefix = ""
    version = ""
    heading = node.select_one("h3.title")
    if heading is not None:
        prefix_el = heading.select_one("span.prefix")
        if prefix_el is not None:
            prefix = prefix_el.get_text(" ", strip=True)
        version_el = heading.select_one("span.version")
        if version_el is not None:
            version = version_el.get_text(" ", strip=True)
        for anchor in heading.select("a"):
            href = anchor.get("href") or ""
            if "prefix_id" in href or "/authors/" in href:
                continue
            found = re.search(r"resources/([^/?#]+)\.(\d+)/?", href)
            if not found:
                continue
            if any(part in href for part in ("/updates", "/reviews", "/download", "/history")):
                continue
            slug = found.group(1)
            title = anchor.get_text(" ", strip=True)
            break
    author = node.select_one('a[href*="resources/authors/"]')
    username = author.get_text(" ", strip=True) if author else ""
    cats: list[int] = []
    cat_title = ""
    for anchor in node.select('a[href*="resources/categories/"]'):
        href = anchor.get("href") or ""
        classes = anchor.get("class") or []
        # On a category page the prefix chip links to the category with ?prefix_id=.
        if "prefixLink" in classes or "prefix_id" in href:
            continue
        cid = _category_from_href(href)
        if cid is None or cid in cats:
            continue
        cats.append(cid)
        if not cat_title:
            cat_title = anchor.get_text(" ", strip=True)
    if not cats and page_category_id is not None:
        cats = [page_category_id]
        cat_title = page_category_title or ""
    tag_el = node.select_one(".tagLine")
    tag_line = tag_el.get_text(" ", strip=True) if tag_el else ""
    rating_avg, rating_count = _rating(node.select_one(".rating"))
    listing_downloads = None
    last_update = None
    for block in node.select("dl"):
        label_el = block.find("dt")
        value_el = block.find("dd")
        if label_el is None or value_el is None:
            continue
        label = label_el.get_text(" ", strip=True).lower()
        if label.startswith("download"):
            listing_downloads = parse_number(value_el.get_text(" ", strip=True))
        elif label.startswith("updated") or "resourceUpdated" in (block.get("class") or []):
            last_update = parse_time_element(block.select_one(".DateTime"))
    details = node.select_one(".resourceDetails")
    resource_date = parse_time_element(details.select_one(".DateTime")) if details else None
    thumb_el = node.select_one("a.resourceIcon img")
    thumb = absolute_url(thumb_el.get("src")) if thumb_el and thumb_el.get("src") else ""
    url = resource_url(slug, forum_id)
    return {
        "forum_id": forum_id,
        "slug": slug,
        "url": url,
        "title": title,
        "prefix_title": prefix,
        "version": version,
        "tag_line": tag_line,
        "username": username,
        "cats": cats,
        "category_title": cat_title,
        "last_update": last_update,
        "resource_date": resource_date,
        "rating_avg": rating_avg,
        "rating_count": rating_count,
        "listing_downloads": listing_downloads,
        "thumb": thumb,
    }


def resource_url(slug: str, forum_id: int) -> str:
    if slug:
        return absolute_url(f"resources/{slug}.{forum_id}/")
    return absolute_url(f"resources/{forum_id}/")


def parse_resource_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    tagid = _unique_id(soup)
    download = soup.select_one('a[href*="download?version="]')
    version_id = None
    filesize_label = None
    slug = ""
    forum_id = None
    if download is not None:
        href = download.get("href") or ""
        found = re.search(r"resources/([^/?#]+)\.(\d+)/download\?version=(\d+)", href)
        if found:
            slug = found.group(1)
            forum_id = int(found.group(2))
            version_id = int(found.group(3))
        else:
            version_match = re.search(r"version=(\d+)", href)
            if version_match:
                version_id = int(version_match.group(1))
        small = download.select_one("small")
        filesize_label = (small or download).get_text(" ", strip=True)
    canonical = soup.select_one('link[rel="canonical"]')
    url = absolute_url(canonical.get("href")) if canonical and canonical.get("href") else ""
    if url:
        found = re.search(r"/resources/([^/?#]+)\.(\d+)/?", url)
        if found:
            slug = slug or found.group(1)
            forum_id = forum_id or int(found.group(2))
    if not url and forum_id is not None:
        url = resource_url(slug, forum_id)
    info = _section_after_heading(soup, "Information")
    version_block = _version_block(soup)
    author = soup.select_one("dl.author a")
    username = author.get_text(" ", strip=True) if author else ""
    cats: list[int] = []
    category_title = ""
    category_scope = info or soup
    for anchor in category_scope.select('a[href*="resources/categories/"]'):
        cid = _category_from_href(anchor.get("href") or "")
        if cid is None or cid in cats:
            continue
        cats.append(cid)
        if not category_title:
            category_title = anchor.get_text(" ", strip=True)
    rating_avg, rating_count = _rating(info.select_one(".rating") if info else None)
    download_count = None
    count_el = soup.select_one("dl.versionDownloadCount dd")
    if count_el is not None:
        download_count = parse_number(count_el.get_text(" ", strip=True))
    first_release = parse_time_element(soup.select_one("dl.firstRelease .DateTime"))
    last_update = parse_time_element(soup.select_one("dl.lastUpdate .DateTime"))
    title, prefix, version = _header_title(soup)
    tag_el = soup.select_one(".resourceInfo p.tagLine") or soup.select_one("p.tagLine")
    tag_line = tag_el.get_text(" ", strip=True) if tag_el else ""
    thumb_el = soup.select_one("img.resourceIcon")
    thumb = absolute_url(thumb_el.get("src")) if thumb_el and thumb_el.get("src") else ""
    description = _description_node(soup)
    description_text = description.get_text(" ", strip=True) if description is not None else ""
    screenshots = _screenshots(description)
    mentions = mentions_versions(description_text)
    requires = dependency_resource_ids(description, self_id=forum_id)
    tags = detect_tags(
        title=title,
        tag_line=tag_line,
        category_title=category_title,
        category_ids=cats,
        description=description_text,
    )
    filename = _filename_near_download(download.get_text(" ", strip=True) if download else "")
    return {
        "forum_id": forum_id,
        "slug": slug,
        "url": url,
        "tagid": tagid,
        "version_id": version_id,
        "title": title,
        "prefix_title": prefix,
        "version": version,
        "tag_line": tag_line,
        "username": username,
        "cats": cats,
        "category_title": category_title,
        "last_update": last_update,
        "resource_date": first_release,
        "first_release": first_release,
        "download_count": download_count if isinstance(download_count, int) else None,
        "rating_avg": rating_avg,
        "rating_count": rating_count,
        "filesize_label": filesize_label,
        "filename": filename,
        "thumb": thumb,
        "screenshots": screenshots,
        "forum_thread": parse_forum_thread(soup),
        "mentions_versions": mentions,
        "requires": requires,
        "tags": tags,
        "has_unique_id_label": "Unique ID" in html,
    }


def _unique_id(soup) -> str:
    for block in soup.select("dl"):
        label = block.find("dt")
        value = block.find("dd")
        if label is None or value is None:
            continue
        if label.get_text(" ", strip=True).lower() == "unique id:":
            return value.get_text(" ", strip=True)
    return ""


def _section_after_heading(soup, heading: str):
    for node in soup.find_all(["h2", "h3"]):
        if node.get_text(" ", strip=True) == heading:
            return node.find_parent("div")
    return None


def _version_block(soup):
    for node in soup.find_all(["h2", "h3"]):
        if node.get_text(" ", strip=True).lower().startswith("version"):
            return node.find_parent("div")
    return None


def _header_title(soup) -> tuple[str, str, str]:
    heading = soup.select_one(".resourceInfo h1") or soup.select_one("h1")
    if heading is None:
        return "", "", ""
    prefix_el = heading.select_one("span.prefix")
    version_el = heading.select_one("span.muted, span.version")
    prefix = prefix_el.get_text(" ", strip=True) if prefix_el else ""
    version = version_el.get_text(" ", strip=True) if version_el else ""
    parts: list[str] = []
    for child in heading.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
    title = " ".join("".join(parts).split())
    return title, prefix, version


def _description_node(soup):
    node = soup.select_one("li.resourceUpdate blockquote.messageText")
    if node is not None:
        return node
    for quote in soup.select("blockquote.messageText"):
        parent_classes = []
        parent = quote
        for _ in range(6):
            parent = parent.parent
            if parent is None:
                break
            parent_classes.extend(parent.get("class") or [])
        if "review" in parent_classes:
            continue
        return quote
    return None


def _screenshots(description) -> list[str]:
    if description is None:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for image in description.find_all("img"):
        src = image.get("src") or image.get("data-src") or ""
        classes = " ".join(image.get("class") or [])
        lowered = src.lower()
        if not src:
            continue
        if any(token in lowered for token in ("avatar", "smilie", "emoji", "xenforo", "logo", "discord", "steam")):
            continue
        if "smilie" in classes.lower():
            continue
        path = lowered.split("?", 1)[0]
        if not path.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            continue
        url = absolute_url(src)
        if url in seen:
            continue
        seen.add(url)
        found.append(url)
    return found


def parse_forum_thread(soup) -> str | None:
    for anchor in soup.select(".resourceTabs a, ul.tabs a"):
        href = anchor.get("href") or ""
        label = anchor.get_text(" ", strip=True).lower()
        if "threads/" in href and label.startswith("discussion"):
            return absolute_url(href)
    return None


def mentions_versions(text: str | None) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in GAME_VERSION_RE.finditer(text):
        parts = match.group(0).split(".")
        if len(parts) < 2:
            continue
        normalized = f"{int(parts[0])}.{int(parts[1])}"
        if normalized in seen:
            continue
        seen.add(normalized)
        found.append(normalized)
    return sorted(found, key=lambda item: [int(part) for part in item.split(".")])


def dependency_resource_ids(description, self_id: int | None = None, window: int = DEPENDENCY_WINDOW) -> list[int]:
    if description is None:
        return []
    chunks: list[str] = []
    length = 0
    links: list[tuple[int, int, int]] = []

    def add_text(text: str) -> None:
        nonlocal length
        chunks.append(text)
        length += len(text)

    def walk(node) -> None:
        for child in getattr(node, "children", []):
            if isinstance(child, NavigableString):
                add_text(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            if child.name in {"script", "style"}:
                continue
            if child.name == "br":
                add_text("\n")
                continue
            if child.name == "a" and child.get("href"):
                resource_id = resource_id_from_href(child.get("href"))
                start = length
                add_text(child.get_text(" ", strip=False))
                if resource_id is not None:
                    links.append((start, length, resource_id))
                continue
            walk(child)

    walk(description)
    text = "".join(chunks)
    ordered: list[int] = []
    seen: set[int] = set()
    for start, end, resource_id in links:
        if self_id is not None and resource_id == self_id:
            continue
        if resource_id in seen:
            continue
        snippet = text[max(0, start - window) : end + window]
        if DEPENDENCY_RE.search(snippet):
            seen.add(resource_id)
            ordered.append(resource_id)
    return ordered


def _filename_near_download(text: str) -> str:
    for token in re.findall(r"[^\s<>\"]+\.zip", text or "", flags=re.I):
        if token.lower() == ".zip":
            continue
        return token
    return ""


def _contains_term(text: str, term: str) -> bool:
    # The hyphen lookahead skips compounds such as "semi-realistic".
    return re.search(rf"\b{re.escape(term)}\b(?!-)", text, re.I) is not None


def detect_tags(
    *,
    title: str = "",
    tag_line: str = "",
    category_title: str = "",
    category_ids: list[int] | None = None,
    description: str = "",
) -> list[str]:
    """Keyword tags. Brands may come from the description; noisier words do not."""
    cats = category_ids or []
    heading = " ".join(part for part in (title, tag_line, category_title) if part)
    brand_source = f"{heading} {description or ''}"
    tags: list[str] = []
    for brand in BRANDS:
        if _contains_term(brand_source, brand):
            tags.append(f"brand:{brand}")
    for kind in VEHICLE_TYPES:
        if _contains_term(heading, kind):
            tags.append(f"vehicle:{kind}")
    if 4 in cats and "vehicle:aircraft" not in tags and "vehicle:plane" not in tags and "vehicle:airplane" not in tags:
        tags.append("vehicle:aircraft")
    if 6 in cats and "vehicle:boat" not in tags:
        tags.append("vehicle:boat")
    category_lower = (category_title or "").lower()
    if (
        9 in cats
        or "terrain" in category_lower
        or _contains_term(heading, "map")
        or _contains_term(heading, "maps")
        or _contains_term(heading, "terrain")
        or _contains_term(heading, "terrains")
    ):
        tags.append("map")
    if any(_contains_term(heading, word) for word in ("pack", "packs", "bundle", "bundles", "collection", "collections")):
        tags.append("pack")
    return list(dict.fromkeys(tags))
