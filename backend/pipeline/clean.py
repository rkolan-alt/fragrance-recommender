"""Clean data/raw/perfumes.csv into data/processed/perfumes.parquet.

Only the columns the recommender uses are kept, plus identity columns
(id, slug, name, brand, year, url) for display, search and linking.
In the raw CSV a missing value is stored as 0 (e.g. rating_avg=0 when
vote_count=0); here those become NaN.
"""

import sys

import numpy as np
import pandas as pd

from app.config import settings
from pipeline.parsing import NOTE_ALIASES, parse_weighted

IDENTITY_COLS = ["id", "slug", "name", "brand", "year", "url"]
LONGEVITY_BUCKETS = [f"longevity_b{i}" for i in range(1, 6)]
SEASONS = ["winter", "spring", "summer", "autumn"]
NOTE_TIERS = ["notes_top", "notes_middle", "notes_base"]
USECOLS = [
    *IDENTITY_COLS,
    "gender",
    "rating_avg",
    "vote_count",
    "longevity_avg",
    *LONGEVITY_BUCKETS,
    *SEASONS,
    "accords",
    *NOTE_TIERS,
    "notes_flat",
]

# Minimum ratings for a perfume to be recommended. Every perfume stays
# searchable so users can add obscure ones they own.
MIN_POOL_VOTES = 30


def to_records(pairs: list[tuple[str, int]]) -> list[dict]:
    return [{"name": name, "weight": weight} for name, weight in pairs]


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw[USECOLS].copy()

    # Ratings: 0 means "no votes".
    df["rating_avg"] = df["rating_avg"].where(df["vote_count"] > 0)

    # Longevity: prefer the given average; fall back to the histogram.
    hist = df[LONGEVITY_BUCKETS].to_numpy(dtype=float)
    df["longevity_votes"] = hist.sum(axis=1).astype(int)
    with np.errstate(invalid="ignore", divide="ignore"):
        hist_avg = (hist * np.arange(1, 6)).sum(axis=1) / hist.sum(axis=1)
    df["longevity_avg"] = df["longevity_avg"].where(df["longevity_avg"] > 0, hist_avg)
    df.loc[df["longevity_votes"] == 0, "longevity_avg"] = np.nan

    # Seasons: share of each season's votes.
    season_votes = df[SEASONS].sum(axis=1)
    df["season_votes"] = season_votes.astype(int)
    for season in SEASONS:
        df[f"season_share_{season}"] = df[season] / season_votes.where(season_votes > 0)
    df["warm_share"] = df["season_share_spring"] + df["season_share_summer"]
    df["cold_share"] = df["season_share_autumn"] + df["season_share_winter"]

    # Accords and notes as lists of {name, weight}.
    df["accords"] = df["accords"].map(lambda v: to_records(parse_weighted(v)))
    for tier in NOTE_TIERS:
        df[tier] = df[tier].map(lambda v: to_records(parse_weighted(v, NOTE_ALIASES)))
    flat = df["notes_flat"].map(lambda v: to_records(parse_weighted(v, NOTE_ALIASES)))
    no_pyramid = df[NOTE_TIERS].map(len).sum(axis=1) == 0
    df.loc[no_pyramid, "notes_middle"] = flat[no_pyramid]
    df = df.drop(columns=["notes_flat", *LONGEVITY_BUCKETS])

    df["year"] = df["year"].astype("Int64")
    df["in_pool"] = (
        (df["vote_count"] >= MIN_POOL_VOTES)
        & (df["accords"].map(len) > 0)
        & df["rating_avg"].notna()
    )
    return df.reset_index(drop=True)


def main() -> int:
    raw_path = settings.data_dir / "raw" / "perfumes.csv"
    out_path = settings.data_dir / "processed" / "perfumes.parquet"
    raw = pd.read_csv(raw_path, usecols=USECOLS, low_memory=False)
    df = clean(raw)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    print(f"{len(df):,} perfumes ({df['in_pool'].sum():,} in pool) → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
