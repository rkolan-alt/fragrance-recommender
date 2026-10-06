"""Report counts and null rates for data/processed/perfumes.parquet."""

import sys

import pandas as pd

from app.config import settings


def main() -> int:
    df = pd.read_parquet(settings.data_dir / "processed" / "perfumes.parquet")
    pool = df[df["in_pool"]]
    notes = df[["notes_top", "notes_middle", "notes_base"]].map(len).sum(axis=1)

    print(f"Perfumes:        {len(df):,}")
    print(f"Candidate pool:  {len(pool):,}")
    print(f"Unique ids:      {df['id'].is_unique}")
    print("\nMissing, whole catalog → pool:")
    checks = {
        "rating": df["rating_avg"].isna(),
        "longevity": df["longevity_avg"].isna(),
        "seasons": df["season_votes"] == 0,
        "accords": df["accords"].map(len) == 0,
        "notes": notes == 0,
    }
    for label, missing in checks.items():
        print(f"  {label:<10} {missing.mean():6.1%} → {missing[df['in_pool']].mean():6.1%}")
    print("\nPool gender mix:")
    print(pool["gender"].value_counts(normalize=True).round(3).to_string())

    problems = []
    if not df["id"].is_unique:
        problems.append("duplicate ids")
    if pool["rating_avg"].isna().any():
        problems.append("pool perfume with no rating")
    if not pool["longevity_avg"].dropna().between(1, 5).all():
        problems.append("longevity_avg outside 1–5")
    shares = pool[["warm_share", "cold_share"]].dropna().sum(axis=1)
    if not ((shares - 1).abs() < 1e-6).all():
        problems.append("season shares don't sum to 1")
    if problems:
        print("\nFAILED: " + "; ".join(problems))
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
