"""Explicit, quota-capped refresh. python -m app.pricing.refresh --top 50"""

import argparse
import asyncio
from collections import Counter

from app.config import settings
from app.db.session import session_factory
from app.engine.catalog import load_catalog
from app.engine.recommend import Filters
from app.pricing.discovery import price_candidates
from app.pricing.service import due_items, load_prices, refresh_one


async def run(args):
    if not settings.serpapi_key:
        print("Set SERPAPI_KEY in the root .env first. No requests made.")
        return 1
    catalog = load_catalog()
    p = catalog.perfumes
    if args.owned_ids:
        async with session_factory() as session:
            prices = await load_prices(session)
            selected = price_candidates(
                catalog,
                args.owned_ids,
                Filters(include_clones=args.include_clones),
                priced_ids=[o.perfume_id for o in prices],
                limit=max(60, args.top),
            )
            # The CLI may prepare more than the background per-request allowance,
            # but every actual query still passes the shared daily quota guard.
            items = []
            for item in selected:
                if await due_items(session, [item]):
                    items.append(item)
                if len(items) >= args.top:
                    break
    else:
        candidates = p[p.in_pool].sort_values("vote_count", ascending=False)
        if args.ids:
            unknown = set(args.ids) - set(p.id)
            if unknown:
                print("Unknown perfume IDs:", sorted(unknown))
                return 1
            candidates = p[p.id.isin(args.ids)]
        items = [
            (int(row.id), row.brand, row.name) for row in candidates.head(args.top).itertuples()
        ]
    counts = Counter()
    for pid, brand, name in items:
        state = await refresh_one(pid, brand, name)
        counts[state] += 1
        if state in {"quota_limited", "error"}:
            break
    print("Refresh results:", dict(counts))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=50)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--ids", type=int, nargs="+")
    mode.add_argument(
        "--owned-ids",
        type=int,
        nargs="+",
        help="Price value-house candidates matched to this collection",
    )
    parser.add_argument("--include-clones", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.top <= 2000:
        parser.error("--top must be 1–2000")
    try:
        return asyncio.run(run(args))
    except (KeyError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
