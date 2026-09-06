"""
Universes are curated lists of titles (e.g. "marvel", "star_wars") stored as
simple JSON files in data/universes/. This is deliberately manual/curated --
there's no reliable API for "give me everything in the Star Wars universe"
that doesn't also pull in unrelated documentaries etc., so the group builds
the list once via /universe addtitle and reuses it for every game.
"""
import json
import re
from pathlib import Path

UNIVERSES_DIR = Path(__file__).parent / "data" / "universes"


def _slugify(name: str) -> str:
    slug = name.strip().lower().replace(" ", "_")
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    return slug


def list_universes() -> list[str]:
    UNIVERSES_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p.stem for p in UNIVERSES_DIR.glob("*.json"))


def load_universe(name: str) -> list[dict]:
    """Returns [{'title': str, 'type': 'movie'|'series'}, ...]. Empty list if not found."""
    path = UNIVERSES_DIR / f"{_slugify(name)}.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_universe(name: str, entries: list[dict]):
    UNIVERSES_DIR.mkdir(parents=True, exist_ok=True)
    path = UNIVERSES_DIR / f"{_slugify(name)}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def add_title(universe: str, title: str, media_type: str) -> bool:
    """Returns False if the title was already in the list (case-insensitive)."""
    entries = load_universe(universe)
    if any(e["title"].lower() == title.lower() for e in entries):
        return False
    entries.append({"title": title, "type": media_type})
    save_universe(universe, entries)
    return True


def remove_title(universe: str, title: str) -> bool:
    entries = load_universe(universe)
    new_entries = [e for e in entries if e["title"].lower() != title.lower()]
    if len(new_entries) == len(entries):
        return False
    save_universe(universe, new_entries)
    return True
