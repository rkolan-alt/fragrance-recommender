"""Explicit, quota-capped refresh. python -m app.pricing.refresh --top 50"""

import argparse
import asyncio
from collections import Counter

from app.config import settings
from app.engine.catalog import load_catalog
from app.pricing.matching import concentration
from app.pricing.service import refresh_one


async def run(args):
    if not settings.serpapi_key:
        print("Set SERPAPI_KEY in the root .env first. No requests made.")
        return 1
    p = load_catalog().perfumes
    candidates = p[p.in_pool].sort_values("vote_count", ascending=False)
    if args.ids:
        unknown = set(args.ids) - set(p.id)
        if unknown:
            print("Unknown perfume IDs:", sorted(unknown))
            return 1
        candidates = p[p.id.isin(args.ids)]
    candidates = candidates[candidates.name.map(concentration).notna()].head(args.top)
    counts = Counter()
    for row in candidates.itertuples():
        state = await refresh_one(int(row.id), row.brand, row.name)
        counts[state] += 1
        if state in {"quota_limited", "error"}:
            break
    print("Refresh results:", dict(counts))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--ids", type=int, nargs="*")
    args = parser.parse_args()
    if not 1 <= args.top <= 2000:
        parser.error("--top must be 1–2000")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
