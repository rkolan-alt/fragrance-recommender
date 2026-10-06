"""Print nearest neighbors in the candidate pool, as a sanity check.

python -m pipeline.neighbors "Dior Sauvage" "Creed Aventus" --k 10
"""

import argparse
import sys

import pandas as pd
import scipy.sparse as sp
from rapidfuzz import fuzz, process

from app.config import settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("queries", nargs="+", help='e.g. "Dior Sauvage"')
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--include-clones", action="store_true")
    args = parser.parse_args()

    processed = settings.data_dir / "processed"
    df = pd.read_parquet(
        processed / "perfumes.parquet", columns=["brand", "name", "vote_count", "in_pool"]
    )
    scores = pd.read_parquet(processed / "scores.parquet")
    matrix = sp.load_npz(processed / "features.npz")
    labels = (df["brand"] + " " + df["name"]).tolist()
    pool = df["in_pool"].to_numpy()
    if not args.include_clones:
        clones = pd.read_parquet(processed / "clones.parquet")
        pool = pool & ~clones["is_clone"].to_numpy()

    for query in args.queries:
        # Prefer the most-voted perfume among close name matches.
        matches = process.extract(query, labels, scorer=fuzz.WRatio, limit=10)
        best = max(
            (m for m in matches if m[1] >= matches[0][1] - 5),
            key=lambda m: df.at[m[2], "vote_count"],
        )
        row = best[2]
        sims = (matrix @ matrix[row].T).toarray().ravel()
        sims[~pool] = -1
        sims[row] = -1
        top = sims.argsort()[::-1][: args.k]
        print(f"\n{labels[row]}  ({df.at[row, 'vote_count']:,} votes)")
        for i in top:
            print(
                f"  {sims[i]:.3f}  {labels[i]:<55} "
                f"votes={df.at[i, 'vote_count']:>6,}  Q={scores.at[i, 'quality']:.2f}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
