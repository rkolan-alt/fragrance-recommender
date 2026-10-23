"""Validation replays the production matcher without new provider queries."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.pricing.client import SerpApiClient
from app.pricing.matching import assess_offer, match_offer
from app.pricing.service import refresh_one
from app.pricing.validate import analyze, sanitized_payload
from tests.test_accounts import account_app  # noqa: F401
from tests.test_pricing import FakeClient, listing


def test_snapshot_drops_credentials_metadata_and_query_parameters():
    payload = {
        "search_parameters": {"api_key": "secret"},
        "search_metadata": {"json_endpoint": "secret"},
        "organic_results": [
            {
                **listing(),
                "api_key": "secret",
                "link": "https://amazon.com/dp/ASIN?api_key=secret#secret",
            },
            {"title": "Unsafe", "link": "https://user:secret@amazon.com/dp/ASIN"},
        ],
    }
    safe = sanitized_payload(payload)
    assert "secret" not in json.dumps(safe)
    assert safe["organic_results"][0]["link"] == "https://amazon.com/dp/ASIN"
    assert set(safe) == {"organic_results"}


def test_recorded_response_can_be_replayed_with_rejection_reasons():
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "serpapi_amazon_sauvage.json").read_text()
    )
    result = analyze(
        {
            "id": 48100,
            "brand": "Dior",
            "name": "Sauvage Eau de Parfum",
            "fetched_at": datetime.now(UTC).isoformat(),
            "payload": sanitized_payload(payload),
        }
    )
    assert len(result["accepted_offers"]) == 2
    assert result["rejection_counts"]["concentration_mismatch_or_missing"] > 0
    assert result["listings"] == len(result["decisions"])


def test_capture_receives_response_before_matching_and_once_per_query():
    captured = []

    async def reserve():
        return True

    client = SerpApiClient(
        "test",
        reserve=reserve,
        response_sink=captured.append,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"organic_results": [listing()]})
        ),
    )
    rows = asyncio.run(client.search("Chanel", "Bleu de Chanel EDP"))
    assert len(captured) == 1
    assert match_offer("Chanel", "Bleu de Chanel EDP", rows[0])


def test_missing_brand_is_accepted_without_using_url_as_evidence():
    row = listing(title="Eros Men 3.4 oz Eau de Parfum Spray", link="https://amazon.com/dp/ASIN")
    offer, reason = assess_offer("Versace", "Eros Eau de Parfum", row)
    assert offer is not None and reason == "accepted"


def test_retry_completed_respects_active_leases_and_quota(account_app, monkeypatch):  # noqa: F811
    from app.config import settings
    from app.db.models import PriceRefresh

    _, factory = account_app
    monkeypatch.setattr(settings, "pricing_daily_request_limit", 2)
    fake = FakeClient()

    async def run():
        kwargs = {"factory": factory, "client": fake, "retry_completed": True}
        assert await refresh_one(1, "Chanel", "Bleu de Chanel EDP", **kwargs) == "ready"
        assert await refresh_one(1, "Chanel", "Bleu de Chanel EDP", **kwargs) == "ready"
        assert await refresh_one(1, "Chanel", "Bleu de Chanel EDP", **kwargs) == "quota_limited"
        async with factory() as session:
            session.add(
                PriceRefresh(
                    perfume_id=2,
                    state="checking",
                    next_refresh_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
            await session.commit()
        assert await refresh_one(2, "Chanel", "Bleu de Chanel EDP", **kwargs) == "cached_or_pending"
        assert fake.calls == 2

    asyncio.run(run())


def test_replay_command_never_calls_provider_or_updates_database(tmp_path, monkeypatch):
    from argparse import Namespace

    from app.pricing import validate
    from tests.test_engine import make_catalog, perfume

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline replay attempted a network or database operation")

    catalog = make_catalog(*(perfume(i) for i in range(1, 8)))
    monkeypatch.setattr(validate, "load_catalog", lambda: catalog)
    monkeypatch.setattr(validate, "refresh_one", forbidden)
    monkeypatch.setattr(validate, "session_factory", forbidden)
    snapshot = {
        "id": 6,
        "brand": "Chanel",
        "name": "Bleu de Chanel EDP",
        "fetched_at": datetime.now(UTC).isoformat(),
        "payload": sanitized_payload({"organic_results": [listing()]}),
    }
    (tmp_path / "response-6.json").write_text(json.dumps(snapshot))
    output = tmp_path / "report"
    args = Namespace(replay=tmp_path, output=output, owned_ids=[1, 2, 3, 4, 5], budget_max=60)
    assert asyncio.run(validate.run(args)) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["coverage"] == 1
    assert report["checks"]["budget_ids"] == [6]
    reviews = json.loads((output / "manual-review.json").read_text())
    reviews[0]["notes"] = "Human review retained"
    (output / "manual-review.json").write_text(json.dumps(reviews))
    assert asyncio.run(validate.run(args)) == 0
    assert (
        json.loads((output / "manual-review.json").read_text())[0]["notes"]
        == "Human review retained"
    )


def test_sanitization_preserves_rejection_of_invalid_primary_link():
    raw = listing(link_clean="https://user:secret@amazon.com/dp/ASIN")
    safe = sanitized_payload({"organic_results": [raw]})
    from app.pricing.client import amazon_offers

    replayed = amazon_offers(safe)[0]
    assert match_offer("Chanel", "Bleu de Chanel EDP", replayed) is None
    assert "secret" not in json.dumps(safe)
