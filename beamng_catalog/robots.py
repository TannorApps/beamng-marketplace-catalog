"""A small robots.txt reader for the catalog crawler."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Robots:
    disallow: list[str] = field(default_factory=list)
    allow: list[str] = field(default_factory=list)
    delay: float | None = None

    def allows(self, path: str) -> bool:
        if not path.startswith("/"):
            path = "/" + path
        best_disallow = -1
        for rule in self.disallow:
            if rule and path.startswith(rule):
                best_disallow = max(best_disallow, len(rule))
        if best_disallow < 0:
            return True
        best_allow = -1
        for rule in self.allow:
            if rule and path.startswith(rule):
                best_allow = max(best_allow, len(rule))
        return best_allow >= best_disallow


def parse_robots(text: str) -> Robots:
    """Rules for User-agent: *. Other agents are ignored."""
    groups: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if current is None or current["locked"]:
                current = {"agents": [], "disallow": [], "allow": [], "delay": None, "locked": False}
                groups.append(current)
            current["agents"].append(value.lower())
            continue
        if current is None:
            continue
        current["locked"] = True
        if key == "disallow":
            current["disallow"].append(value)
        elif key == "allow":
            current["allow"].append(value)
        elif key == "crawl-delay":
            try:
                current["delay"] = float(value)
            except ValueError:
                pass
    for group in groups:
        if "*" in group["agents"]:
            return Robots(group["disallow"], group["allow"], group["delay"])
    return Robots()
