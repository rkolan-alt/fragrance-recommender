"""Flag known clones and record which original(s) each one copies.

Reads Fragrantica's "smells like" votes (`similar.reminds_me_of`) from
data/raw/perfumes.jsonl. A pair is used in both directions: if Aventus's
page says it smells like Club de Nuit Intense, that counts as evidence too.

For perfume p, perfume r is an original of p when:
  - r is from a different brand,
  - the pair has ≥ CLONE_MIN_UP_VOTES up votes and ≥ CLONE_MIN_AGREEMENT agreement,
  - r came first: an earlier release year, or (years unknown/equal) r has
    ≥ CLONE_ORIGINAL_VOTE_RATIO × p's ratings.

p is a clone when its brand is a dupe house, or it's from a mixed house and
has at least one original. Output: data/processed/clones.parquet with
id, is_clone, clone_of (list of original ids, strongest first).
"""

import json
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

import pandas as pd

from app.config import settings
from app.engine import config


def read_similar_votes(lines: Iterable[str]) -> pd.DataFrame:
    """Return one row per (a, b, up, down) "smells like" pair."""
    rows = []
    for line in lines:
        record = json.loads(line)
        for entry in (record.get("similar") or {}).get("reminds_me_of") or []:
            rows.append(
                (
                    record["id"],
                    entry["id"],
                    entry.get("up_votes") or 0,
                    entry.get("down_votes") or 0,
                )
            )
    return pd.DataFrame(rows, columns=["a", "b", "up", "down"])


def _nfc(names: set[str]) -> set[str]:
    return {unicodedata.normalize("NFC", n) for n in names}


def find_clones(perfumes: pd.DataFrame, votes: pd.DataFrame) -> pd.DataFrame:
    """perfumes: id, brand, year, vote_count. votes: a, b, up, down."""
    # Use each pair in both directions; keep the stronger evidence.
    both = pd.concat([votes, votes.rename(columns={"a": "b", "b": "a"})], ignore_index=True)
    both = both.sort_values("up", ascending=False).drop_duplicates(["a", "b"])
    agreement = both["up"] / (both["up"] + both["down"]).clip(lower=1)
    both = both[
        (both["up"] >= config.CLONE_MIN_UP_VOTES) & (agreement >= config.CLONE_MIN_AGREEMENT)
    ]

    info = perfumes.set_index("id")[["brand", "year", "vote_count"]]
    pairs = (
        both.join(info, on="a")
        .join(info, on="b", rsuffix="_orig")
        .dropna(subset=["brand", "brand_orig"])
    )
    years_known = pairs["year"].notna() & pairs["year_orig"].notna()
    earlier = years_known & (pairs["year_orig"] < pairs["year"])
    not_later = ~years_known | (pairs["year_orig"] <= pairs["year"])
    more_popular = (
        pairs["vote_count_orig"] >= config.CLONE_ORIGINAL_VOTE_RATIO * pairs["vote_count"]
    )
    originals = pairs[
        (pairs["brand"] != pairs["brand_orig"]) & (earlier | (more_popular & not_later))
    ]

    clone_of: dict[int, list[int]] = defaultdict(list)
    for a, b in originals.sort_values("up", ascending=False)[["a", "b"]].itertuples(index=False):
        clone_of[int(a)].append(int(b))

    # Brand names can mix composed/decomposed accents (é vs e + ́).
    brand = perfumes["brand"].map(lambda b: unicodedata.normalize("NFC", b))
    is_dupe_house = brand.isin(_nfc(config.DUPE_HOUSES))
    has_original = perfumes["id"].isin(clone_of.keys())
    return pd.DataFrame(
        {
            "id": perfumes["id"],
            "is_clone": is_dupe_house | (brand.isin(_nfc(config.MIXED_HOUSES)) & has_original),
            "clone_of": [clone_of.get(int(i), []) for i in perfumes["id"]],
        }
    )


def main() -> int:
    raw = settings.data_dir / "raw" / "perfumes.jsonl"
    processed = settings.data_dir / "processed"
    if not raw.exists():
        print(f"Missing {raw}: download perfumes.jsonl from Kaggle into data/raw/")
        return 1
    with raw.open() as f:
        votes = read_similar_votes(f)
    perfumes = pd.read_parquet(
        processed / "perfumes.parquet", columns=["id", "brand", "year", "vote_count", "in_pool"]
    )
    clones = find_clones(perfumes, votes)
    clones.to_parquet(processed / "clones.parquet", index=False)
    in_pool = perfumes["in_pool"].to_numpy()
    print(
        f"{len(votes):,} smells-like pairs; clones: {clones['is_clone'].sum():,} "
        f"({clones['is_clone'][in_pool].sum():,} in pool)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
