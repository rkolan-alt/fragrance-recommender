"""Parsers for the pipe-separated `name:weight` columns in perfumes.csv."""

import math

# Spelling variants that should count as the same note.
NOTE_ALIASES: dict[str, str] = {
    "virginia cedar": "cedar",
    "atlas cedar": "cedar",
    "cedarwood": "cedar",
    "woodsy notes": "woody notes",
    "tonka": "tonka bean",
    "white musk": "musk",
    "madagascar vanilla": "vanilla",
    "vanille": "vanilla",
    "patchouli leaf": "patchouli",
    "oud": "agarwood (oud)",
    "agarwood": "agarwood (oud)",
    "baie rose": "pink pepper",  # French for pink pepper, not a rose
}


def normalize_name(name: str, aliases: dict[str, str] | None = None) -> str:
    key = " ".join(name.strip().lower().split())
    if aliases:
        key = aliases.get(key, key)
    return key


def parse_weighted(value: object, aliases: dict[str, str] | None = None) -> list[tuple[str, int]]:
    """Parse `Bergamot:49|Lemon:5` into [("bergamot", 49), ("lemon", 5)].

    Each entry is split on its last `:`. A name can itself contain `|`
    (e.g. `Eustoma | Lisianthus:83`), so a piece with no numeric weight is
    joined onto the next piece. Duplicate names keep their highest weight.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    text = str(value).strip()
    if not text:
        return []

    weights: dict[str, int] = {}
    pending = ""
    for piece in text.split("|"):
        piece = pending + piece
        name, sep, weight = piece.rpartition(":")
        if not sep or not weight.strip().isdigit():
            pending = piece + "|"
            continue
        pending = ""
        key = normalize_name(name, aliases)
        if key:
            weights[key] = max(weights.get(key, 0), int(weight))
    return list(weights.items())
