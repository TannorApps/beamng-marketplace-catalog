"""Public BeamNG resource categories included in the catalog.

Ids and titles match the in-game repository categories. Slugs are the ones
used on beamng.com category URLs.
"""

from __future__ import annotations

# (category id, url slug, title)
CATEGORIES: list[tuple[int, str, str]] = [
    (3, "land", "Land"),
    (4, "air", "Air"),
    (5, "props", "Props"),
    (6, "boats", "Boats"),
    (7, "mods-of-mods", "Mods of Mods"),
    (8, "scenarios", "Scenarios"),
    (9, "terrains-levels-maps", "Terrains, Levels, Maps"),
    (10, "user-interface-apps", "User Interface Apps"),
    (12, "skins", "Skins"),
    (13, "sounds", "Sounds"),
    (14, "configurations", "Configurations"),
    (15, "license-plates", "License Plates"),
]

CATEGORY_TITLES = {cid: title for cid, _slug, title in CATEGORIES}


def category_page_url(slug: str, category_id: int, page: int) -> str:
    base = f"https://www.beamng.com/resources/categories/{slug}.{category_id}/"
    if page <= 1:
        return base + "?order=last_update"
    return base + f"?order=last_update&page={page}"


def resource_page_url(slug: str, forum_id: int) -> str:
    return f"https://www.beamng.com/resources/{slug}.{forum_id}/"
