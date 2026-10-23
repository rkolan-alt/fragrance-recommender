"""Replay saved Amazon responses, or explicitly collect a quota-capped live sample.

python -m app.pricing.validate --live --limit 10
python -m app.pricing.validate --replay data-directory
"""

import argparse
import asyncio
import json
import math
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.config import settings
from app.db.session import session_factory
from app.engine.catalog import load_catalog
from app.engine.categories import recommend_rows
from app.engine.recommend import Filters
from app.pricing.client import amazon_offers
from app.pricing.matching import IdentityIndex, assess_offer, match_product_link
from app.pricing.service import Price, load_prices, refresh_one

DEFAULT_IDS = [62583, 62762, 25967, 48100, 67502, 39355, 48115, 70090]
DEFAULT_OWNED = [31861, 9099, 9828, 5521, 33519]
# Only public product fields needed for replay. Provider metadata, search URLs,
# request parameters, API keys and account information are never retained.
PUBLIC_FIELDS = {
    "title",
    "price",
    "extracted_price",
    "currency",
    "stock",
    "no_featured_offers_available",
    "monthly_payment_duration",
    "installments_description",
    "multiple_sources",
}


def sanitized_payload(payload):
    rows = []
    for raw in payload.get("organic_results") or []:
        if not isinstance(raw, dict):
            continue
        row = {
            key: value
            for key, value in raw.items()
            if key in PUBLIC_FIELDS
            and isinstance(value, (str, int, float, bool))
            and (not isinstance(value, float) or math.isfinite(value))
        }
        for key in ("link", "link_clean"):
            value = raw.get(key)
            if not isinstance(value, str):
                continue
            row[key] = "redacted-invalid-url"
            try:
                url = urlsplit(value)
                # Drop URLs with credentials and all query/fragment parameters.
                if url.scheme == "https" and not url.username and not url.password:
                    row[key] = urlunsplit((url.scheme, url.netloc, url.path, "", ""))
            except ValueError:
                pass
        rows.append(row)
    return {"organic_results": rows}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False) + "\n")


def analyze(snapshot, identity_index=None):
    decisions = []
    accepted = {}
    product_link = None
    raw_rows = snapshot["payload"]["organic_results"]
    for index, raw in enumerate(raw_rows):
        if raw.get("no_featured_offers_available"):
            offer, reason = None, "no_featured_offer"
        else:
            normalized = amazon_offers({"organic_results": [raw]})[0]
            offer, reason = assess_offer(
                snapshot["brand"], snapshot["name"], normalized, identity_index=identity_index
            )
            if identity_index is not None and product_link is None:
                product_link = match_product_link(
                    snapshot["brand"], snapshot["name"], normalized, identity_index=identity_index
                )
        decisions.append({"index": index, "title": raw.get("title"), "reason": reason})
        if offer:
            accepted[offer.url] = offer
    return {
        "id": snapshot["id"],
        "brand": snapshot["brand"],
        "name": snapshot["name"],
        "fetched_at": snapshot["fetched_at"],
        "listings": len(raw_rows),
        "accepted_offers": [asdict(offer) for offer in accepted.values()],
        "amazon_link": asdict(product_link) if product_link else None,
        "rejection_counts": dict(
            Counter(d["reason"] for d in decisions if d["reason"] != "accepted")
        ),
        "decisions": decisions,
    }


def replay_prices(results):
    return tuple(
        Price(result["id"], **offer, fetched_at=result["fetched_at"])
        for result in results
        for offer in result["accepted_offers"]
    )


def integration_checks(catalog, owned_ids, prices, budget_max):
    rows = recommend_rows(catalog, owned_ids, Filters(budget_max=budget_max), prices=prices)
    budget = next(row for row in rows if row.key == "budget")
    ids = {item.id for item in budget.items}
    affordable = {p.perfume_id for p in prices if p.price <= budget_max}
    return {
        "owned_ids": owned_ids,
        "budget_max": budget_max,
        "budget_ids": sorted(ids),
        "budget_has_candidate": bool(ids),
        "budget_prices_within_cap": ids <= affordable,
        "owned_excluded": not any(item.id in owned_ids for row in rows for item in row.items),
        "clones_excluded": not any(
            catalog.is_clone[catalog.row_of[item.id]] for row in rows for item in row.items
        ),
        "note": "Empty Budget rows do not establish affordable live coverage.",
    }


async def run(args):
    catalog = load_catalog()
    identity_index = IdentityIndex(
        catalog.perfumes[["brand", "name"]].itertuples(index=False, name=None)
    )
    # Validate collection input before any paid requests.
    integration_checks(catalog, args.owned_ids, (), args.budget_max)
    output = args.output
    results, states = [], []
    if args.replay:
        files = sorted(args.replay.glob("response-*.json"))
        if not files:
            raise ValueError("No response-*.json files found for replay")
        results = [analyze(json.loads(path.read_text()), identity_index) for path in files]
    else:
        if not settings.serpapi_key:
            raise ValueError("Set SERPAPI_KEY in the ignored root .env before live validation")
        p = catalog.perfumes
        ids = args.ids or DEFAULT_IDS
        if set(ids) - set(p.id):
            raise ValueError("Unknown sample perfume IDs")
        selected = list(dict.fromkeys(ids))
        if not args.ids:
            # Fill remaining slots with popular, different-brand fragrances.
            brands = set(p[p.id.isin(ids)].brand)
            for row in p[p.in_pool].sort_values("vote_count", ascending=False).itertuples():
                if row.brand not in brands:
                    selected.append(int(row.id))
                    brands.add(row.brand)
                if len(selected) >= args.limit:
                    break
        for pid in selected[: args.limit]:
            row = p.loc[p.id == pid].iloc[0]
            snapshot = None

            def capture(payload, pid=pid, row=row):
                nonlocal snapshot
                snapshot = {
                    "id": pid,
                    "brand": row.brand,
                    "name": row["name"],
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "payload": sanitized_payload(payload),
                }
                # Save before matching so rejected responses remain diagnosable.
                write_json(output / f"response-{pid}.json", snapshot)

            state = await refresh_one(
                pid,
                row.brand,
                row["name"],
                response_sink=capture,
                retry_completed=args.retry_cached,
                identity_index=identity_index,
            )
            states.append({"id": pid, "state": state})
            if snapshot is not None:
                results.append(analyze(snapshot, identity_index))
            print(f"{pid} {row.brand} {row['name']}: {state}", flush=True)
            if state in {"quota_limited", "error"}:
                break
    prices = replay_prices(results)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "replay" if args.replay else "live",
        "states": states,
        "fragrances_observed": len(results),
        "fragrances_with_matches": sum(bool(r["accepted_offers"]) for r in results),
        "coverage": sum(bool(r["accepted_offers"]) for r in results) / len(results)
        if results
        else None,
        "manual_accuracy": "not measured; review accepted Amazon pages separately",
        "results": results,
        "checks": integration_checks(catalog, args.owned_ids, prices, args.budget_max),
    }
    if not args.replay:
        async with session_factory() as session:
            cached = await load_prices(session)
        report["current_database_checks"] = integration_checks(
            catalog, args.owned_ids, cached, args.budget_max
        )
        # Exercise the public API without starting a second server or spending queries.
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from app.main import app

        with patch.object(settings, "pricing_auto_refresh", False):
            with TestClient(app) as client:
                response = client.post(
                    "/recommend",
                    json={
                        "owned_ids": args.owned_ids,
                        "categories": ["budget"],
                        "filters": {"budget_max": args.budget_max},
                    },
                )
                items = response.json().get("rows", [{}])[0].get("items", [])
                tight = client.post(
                    "/recommend",
                    json={
                        "owned_ids": args.owned_ids,
                        "categories": ["budget"],
                        "filters": {"price_max": 1},
                    },
                )
                tight_items = tight.json().get("rows", [{}])[0].get("items", [])
                report["api_checks"] = {
                    "status": response.status_code,
                    "tight_filter_status": tight.status_code,
                    "tight_filter_within_cap": all(
                        item.get("best_offer") and item["best_offer"]["price"] <= 1
                        for item in tight_items
                    ),
                    "budget_ids": [item["id"] for item in items],
                    "prices_within_budget": all(
                        item.get("best_offer") and item["best_offer"]["price"] <= args.budget_max
                        for item in items
                    ),
                    "details": [
                        {"id": r["id"], "status": client.get(f"/perfume/{r['id']}").status_code}
                        for r in results
                        if r["accepted_offers"]
                    ],
                }
    write_json(output / "report.json", report)
    reviews = [
        {
            "perfume_id": r["id"],
            "url": offer["url"],
            "expected_title": offer["title"],
            "expected_price": offer["price"],
            "expected_size_ml": offer["size_ml"],
            "checked_at": None,
            "variant_correct": None,
            "size_correct": None,
            "observed_price": None,
            "available": None,
            "notes": "",
        }
        for r in results
        for offer in r["accepted_offers"]
    ]
    # Append new offers while preserving human review entries on replay/rerun.
    review_path = output / "manual-review.json"
    previous = json.loads(review_path.read_text()) if review_path.exists() else []
    by_key = {(item["perfume_id"], item["url"]): item for item in previous}
    for item in reviews:
        key = (item["perfume_id"], item["url"])
        if key not in by_key:
            by_key[key] = item
    write_json(review_path, list(by_key.values()))
    print(
        f"Report: {output / 'report.json'}; "
        f"matched {report['fragrances_with_matches']}/{len(results)}"
    )
    return 0 if results else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=settings.data_dir
        / "processed"
        / "pricing-validation"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
    )
    parser.add_argument("--ids", type=int, nargs="+")
    parser.add_argument("--owned-ids", type=int, nargs="+", default=DEFAULT_OWNED)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--budget-max", type=float, default=60)
    parser.add_argument(
        "--retry-cached",
        action="store_true",
        help="Recheck completed ready/no-match searches; quota and active leases still apply",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 15 or not 0 < args.budget_max <= 10000:
        parser.error("limit must be 1–15 and budget-max must be >0 and <=10000")
    try:
        return asyncio.run(run(args))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
