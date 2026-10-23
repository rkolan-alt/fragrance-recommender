"""Read-only checks across real catalog collections; performs no retailer searches."""

import argparse
import asyncio
import json
import time
from pathlib import Path

from app.config import settings
from app.db.session import session_factory
from app.engine.catalog import load_catalog
from app.engine.categories import recommend_rows
from app.engine.recommend import Filters, candidate_mask
from app.pricing.discovery import VALUE_HOUSES
from app.pricing.service import load_prices


def collections(catalog):
    p = catalog.perfumes
    popular = p.sort_values("vote_count", ascending=False)

    def choose(mask):
        return [int(v) for v in popular.loc[mask.reindex(popular.index), "id"].head(5)]

    result = {
        "fresh": [31861, 9099, 9828, 5521, 33519],
        "sweet": [75805, 65414, 62615, 93628, 78560],
        "middle_eastern": [88175, 84302, 50582, 106835, 98695],
        "niche": choose(
            p.brand.isin(
                ["Amouage", "Serge Lutens", "Frederic Malle", "Maison Francis Kurkdjian", "Xerjoff"]
            )
        ),
        "feminine": choose(p.gender.eq("female") & p.in_pool),
        "clone_heavy": choose(p.brand.str.casefold().isin(VALUE_HOUSES) & catalog.is_clone),
    }
    for name, ids in result.items():
        if len(set(ids)) < 5:
            raise ValueError(f"Insufficient catalog entries for {name}")
        catalog.rows(ids)
    return result


async def run(output: Path):
    catalog = load_catalog()
    async with session_factory() as session:
        prices = await load_prices(session)
    scenarios = collections(catalog)
    reports = []
    first_rows = {}
    for name, owned in scenarios.items():
        for label, filters in [
            ("default", Filters()),
            ("include_clones", Filters(include_clones=True)),
            ("high_rating", Filters(min_rating=4.3)),
            ("long_lasting", Filters(min_longevity=4)),
            ("priced", Filters(price_max=60)),
            ("empty", Filters(min_votes=10**9)),
        ]:
            before = time.perf_counter()
            rows = recommend_rows(catalog, owned, filters, 12, prices=prices)
            elapsed = round((time.perf_counter() - before) * 1000, 2)
            mask = candidate_mask(catalog, catalog.rows(owned), filters, prices)
            for row in rows:
                ids = [item.id for item in row.items]
                assert len(ids) == len(set(ids)), f"Duplicates: {name}/{row.key}"
                assert all(mask[catalog.row_of[pid]] for pid in ids), (
                    f"Filter/exclusion violation: {name}/{row.key}"
                )
            if label == "default":
                assert rows[0].items, f"No For You results for {name}"
                first_rows[name] = [item.id for item in rows[0].items]
            if label == "empty":
                assert all(not row.items for row in rows)
            reports.append(
                {
                    "collection": name,
                    "filters": label,
                    "duration_ms": elapsed,
                    "row_sizes": {row.key: len(row.items) for row in rows},
                }
            )
    assert first_rows["fresh"] != first_rows["sweet"], (
        "Fresh and sweet collections received identical top results"
    )
    result = {
        "status": "passed",
        "catalog_rows": len(catalog.perfumes),
        "cached_price_offers": len(prices),
        "scenarios": scenarios,
        "checks": reports,
        "note": "Empty priced/Budget rows reflect cached offers; no live searches were made.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                "status": "passed",
                "collections": len(scenarios),
                "filter_runs": len(reports),
                "max_duration_ms": max(item["duration_ms"] for item in reports),
                "report": str(output),
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=settings.data_dir / "processed" / "release-check.json"
    )
    asyncio.run(run(parser.parse_args().output))


if __name__ == "__main__":
    main()
