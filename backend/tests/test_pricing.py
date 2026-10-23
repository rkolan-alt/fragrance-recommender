"""Synthetic provider fixtures: no credentials or live network calls."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.db.models import Offer, PricingQuota
from app.pricing.client import PricingError, SerpApiClient
from app.pricing.matching import match_offer, size_ml
from app.pricing.service import Price, load_prices, refresh_one, summary
from tests.test_accounts import account_app  # noqa: F401


def listing(**overrides):
    return {
        "title": "Chanel Bleu de Chanel Eau de Parfum Spray 100 ml",
        "source": "Amazon",
        "extracted_price": 59.99,
        "price": "$59.99",
        "link": "https://www.amazon.com/dp/B000000000",
        **overrides,
    }


def test_match_exact_variant_but_reject_flankers():
    assert match_offer("Chanel", "Bleu de Chanel Eau de Parfum", listing())
    assert not match_offer(
        "Chanel",
        "Bleu de Chanel Eau de Parfum",
        listing(title="Chanel Bleu de Chanel Eau de Toilette 100 ml"),
    )
    assert not match_offer(
        "Chanel",
        "Bleu de Chanel Eau de Parfum",
        listing(title="Chanel Bleu de Chanel Intense Eau de Parfum 100 ml"),
    )
    assert not match_offer("Chanel", "Bleu de Chanel", listing())  # no assumed concentration


@pytest.mark.parametrize(
    "patch",
    [
        {"source": "Amazon", "link": "https://www.amazon.com.evil.example/product"},
        {"source": "Jomashop deals", "link": "https://www.jomashop.com/a"},
        {"link": "javascript:alert(1)"},
        {"link": "http://www.jomashop.com/a"},
        {"link": "https://evil@www.jomashop.com/a"},
        {"link": None},
        {"currency": "CAD"},
        {"price": "CA$59.99"},
        {"extracted_price": "NaN"},
        {"extracted_price": -1},
        {"extracted_price": "Infinity"},
        {"multiple_sources": True},
        {"link": "https://www.google.com/search?product=1"},
    ],
)
def test_reject_untrusted_or_noncomparable_offer(patch):
    assert match_offer("Chanel", "Bleu de Chanel Eau de Parfum", listing(**patch)) is None


@pytest.mark.parametrize(
    "suffix",
    [
        "Tester",
        "Gift Set",
        "Refill",
        "Sample",
        "Decant",
        "Lotion",
        "Travel Spray",
        "2 x 100 ml",
        "Inspired by",
    ],
)
def test_reject_nonretail_bottles(suffix):
    raw = listing(title=f"Chanel Bleu de Chanel EDP 100 ml {suffix}")
    assert match_offer("Chanel", "Bleu de Chanel Eau de Parfum", raw) is None


def test_size_and_brand_alias():
    assert size_ml("3.4 fl oz (100 ml)") == pytest.approx(100.5, abs=1)
    assert size_ml("10 ml") is None
    assert size_ml("3.4 oz 200 ml") is None
    assert match_offer(
        "Dior",
        "Sauvage Eau de Parfum",
        listing(title="Christian Dior Sauvage EDP 3.4 oz. (100 ml)"),
    )
    assert match_offer(
        "Giorgio Armani",
        "Acqua di Gio Eau de Parfum",
        listing(title="Armani Acqua di Gio EDP 100 ml"),
    )


def price(store="amazon", amount="50", size=100, pid=6):
    return Price(
        pid,
        store,
        Decimal(amount),
        size,
        "edp",
        f"https://{store}.com/p",
        "Perfume EDP 100 ml",
        datetime.now(UTC).isoformat(),
    )


def test_comparison_separates_bottle_cost_from_unit_value():
    prices = (price(amount="45", size=50), price("amazon", "85", 100), price(amount="80"))
    result = summary(prices, "Brand", "Name")
    assert result["best_offer"]["price"] == 80  # comparable 100 ml pair
    assert result["best_value_offer"]["price"] == 80
    budget = summary(prices, "Brand", "Name", price_max=60)
    assert budget["best_offer"]["price"] == 45
    assert budget["best_offer"]["size_ml"] == 50
    assert summary((), "Brand", "Name")["best_offer"] is None


def test_provider_parameters_and_single_request():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"organic_results": [listing()]})

    client = SerpApiClient("test-key", transport=httpx.MockTransport(handler))
    assert len(asyncio.run(client.search("Chanel", "Bleu de Chanel EDP"))) == 1
    assert len(requests) == 1
    assert requests[0].url.params["engine"] == "amazon"
    assert requests[0].url.params["amazon_domain"] == "amazon.com"
    assert "Bleu de Chanel EDP" in requests[0].url.params["k"]


@pytest.mark.parametrize("status, payload", [(429, {}), (200, {"error": "quota"}), (200, [])])
def test_provider_error_does_not_expose_api_key(status, payload):
    c = SerpApiClient(
        "secret-test-key",
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json=payload)),
    )
    with pytest.raises(PricingError) as error:
        asyncio.run(c.search("Brand", "Name"))
    assert "secret-test-key" not in str(error.value)


class FakeClient:
    def __init__(self, fail=False, empty=False):
        self.calls, self.fail, self.empty = 0, fail, empty

    async def search(self, brand, name):
        self.calls += 1
        if self.fail:
            raise PricingError("test error")
        return [] if self.empty else [listing()]


def test_database_cache_quota_and_negative_cache(account_app, monkeypatch):  # noqa: F811
    _, factory = account_app
    monkeypatch.setattr(settings, "pricing_daily_request_limit", 2)
    fake = FakeClient()

    async def run():
        assert (
            await refresh_one(1, "Chanel", "Bleu de Chanel EDP", factory=factory, client=fake)
            == "ready"
        )
        assert (
            await refresh_one(1, "Chanel", "Bleu de Chanel EDP", factory=factory, client=fake)
            == "cached_or_pending"
        )
        assert fake.calls == 1
        async with factory() as session:
            offers = await load_prices(session)
            assert len(offers) == 1 and offers[0].price == Decimal("59.99")
        empty = FakeClient(empty=True)
        assert (
            await refresh_one(2, "Chanel", "Bleu de Chanel EDP", factory=factory, client=empty)
            == "no_match"
        )
        assert (
            await refresh_one(2, "Chanel", "Bleu de Chanel EDP", factory=factory, client=empty)
            == "cached_or_pending"
        )
        assert (
            await refresh_one(3, "Chanel", "Bleu de Chanel EDP", factory=factory, client=fake)
            == "quota_limited"
        )
        assert fake.calls == 1
        async with factory() as session:
            assert (await session.scalar(select(PricingQuota))).requests == 2

    asyncio.run(run())


def test_stale_prices_are_not_used_and_failed_refresh_preserves_history(account_app):  # noqa: F811
    _, factory = account_app

    async def run():
        async with factory() as session:
            session.add(
                Offer(
                    perfume_id=1,
                    store="amazon",
                    price=Decimal("40"),
                    size_ml=100,
                    concentration="edp",
                    title="Old",
                    url="https://amazon.com/dp/B000000000",
                    fetched_at=datetime.now(UTC) - timedelta(days=8),
                )
            )
            await session.commit()
            assert await load_prices(session) == ()
        failed = FakeClient(fail=True)
        assert (
            await refresh_one(1, "Chanel", "Bleu de Chanel EDP", factory=factory, client=failed)
            == "error"
        )
        async with factory() as session:
            assert await session.scalar(select(Offer)) is not None

    asyncio.run(run())


def test_refresh_lease_prevents_duplicate_concurrent_provider_calls(account_app):  # noqa: F811
    _, factory = account_app
    fake = FakeClient()

    async def run():
        states = await asyncio.gather(
            *[
                refresh_one(1, "Chanel", "Bleu de Chanel EDP", factory=factory, client=fake)
                for _ in range(3)
            ]
        )
        assert states.count("ready") == 1
        assert fake.calls == 1

    asyncio.run(run())


def test_lazy_refresh_skips_cached_but_allows_unqualified_names(account_app):  # noqa: F811
    from app.pricing.service import due_items

    _, factory = account_app

    async def run():
        await refresh_one(1, "Chanel", "Bleu de Chanel EDP", factory=factory, client=FakeClient())
        async with factory() as session:
            due = await due_items(
                session,
                [
                    (1, "Chanel", "Bleu de Chanel EDP"),
                    (2, "Chanel", "Bleu de Chanel"),
                    (3, "Chanel", "Bleu de Chanel EDP"),
                ],
            )
            assert [i[0] for i in due] == [2, 3]

    asyncio.run(run())


def test_exhausted_quota_prevents_network_request():
    from app.pricing.client import PricingQuotaError

    async def reserve():
        return False

    def handler(request):
        pytest.fail("Quota-exhausted requests must not reach provider")

    provider = SerpApiClient("key", transport=httpx.MockTransport(handler), reserve=reserve)
    with pytest.raises(PricingQuotaError):
        asyncio.run(provider.search("Chanel", "Bleu de Chanel EDP"))


@pytest.mark.parametrize(
    "patch",
    [
        {"details_and_offers": ["Out of stock"]},
        {"monthly_payment_duration": 6},
        {"installments_description": "Pay in 4"},
    ],
)
def test_reject_unavailable_and_installment_prices(patch):
    assert match_offer("Chanel", "Bleu de Chanel Eau de Parfum", listing(**patch)) is None


def test_recorded_live_amazon_response_matches_correct_sauvage_variants():
    import json
    from pathlib import Path

    from app.pricing.client import amazon_offers

    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "serpapi_amazon_sauvage.json").read_text()
    )
    matches = [
        m
        for row in amazon_offers(fixture)
        if (m := match_offer("Dior", "Sauvage Eau de Parfum", row))
    ]
    assert {m.price for m in matches} == {Decimal("130.99"), Decimal("99.98")}
    assert all(m.store == "amazon" and m.concentration == "edp" for m in matches)
    assert all("Elixir" not in m.title for m in matches)


def test_amazon_only_summary_excludes_legacy_retailer():
    result = summary((price(), price("jomashop", "10")), "Brand", "Name")
    assert result["pricing_source"] == "amazon"
    assert result["best_offer"]["price"] == 50
    assert result["search_links"] == {}
    assert all(p["store"] == "amazon" for p in result["offers"])
    assert "comparison_complete" not in result


def test_one_query_reservation_per_amazon_search():
    attempts = 0

    async def reserve():
        nonlocal attempts
        attempts += 1
        return attempts == 1

    def handler(request):
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    {
                        "title": "Chanel Bleu de Chanel EDP 100 ml",
                        "price": "$120.00",
                        "extracted_price": 120,
                        "link_clean": "https://www.amazon.com/dp/B000000000",
                    }
                ]
            },
        )

    provider = SerpApiClient("key", transport=httpx.MockTransport(handler), reserve=reserve)
    rows = asyncio.run(provider.search("Chanel", "Bleu de Chanel Eau de Parfum"))
    assert len(rows) == 1
    assert attempts == 1
    assert match_offer("Chanel", "Bleu de Chanel Eau de Parfum", rows[0]).store == "amazon"


def test_fresh_legacy_retailer_is_not_loaded(account_app):  # noqa: F811
    _, factory = account_app

    async def run():
        async with factory() as session:
            session.add(
                Offer(
                    perfume_id=1,
                    store="jomashop",
                    price=Decimal("10"),
                    size_ml=100,
                    concentration="edp",
                    title="Legacy",
                    url="https://jomashop.com/product",
                    fetched_at=datetime.now(UTC),
                )
            )
            await session.commit()
            assert await load_prices(session) == ()

    asyncio.run(run())


@pytest.mark.parametrize(
    "title",
    [
        "Eros Men 3.4 oz Eau de Parfum Spray",
        "Versace Eros Men 3.4 oz Eau de Parfum Spray",
    ],
)
def test_brand_optional_when_exact_scent_and_variant_match(title):
    assert match_offer("Versace", "Eros Eau de Parfum", listing(title=title))


@pytest.mark.parametrize(
    "title",
    [
        "Armaf Eros Eau de Parfum 100 ml",
        "Eros Flame Eau de Parfum 100 ml",
        "Eros Energy Eau de Parfum 100 ml",
        "Eros Eau de Toilette 100 ml",
        "Eros Eau de Parfum 10 ml Sample",
        "Eau de Parfum 100 ml",
    ],
)
def test_optional_brand_still_rejects_conflicting_identity_and_variants(title):
    assert match_offer("Versace", "Eros Eau de Parfum", listing(title=title)) is None


def test_brand_named_scent_cannot_match_an_anonymous_listing():
    assert match_offer("Chloé", "Chloé Eau de Parfum", listing(title="EDP Spray 75 ml")) is None
    assert match_offer("Chloé", "Chloé Eau de Parfum", listing(title="Chloe EDP Spray 75 ml"))


def test_brand_optional_does_not_accept_a_mixed_concentration_bundle():
    title = (
        "Eros for Men Eau de Parfum Spray, 6.7 Ounce & Eros for Men 6.7 oz Eau de Toilette Spray"
    )
    assert match_offer("Versace", "Eros Eau de Parfum", listing(title=title)) is None


def test_catalog_resolves_descriptive_words_and_flankers():
    from app.pricing.matching import IdentityIndex

    index = IdentityIndex(
        [
            ("Montblanc", "Legend Eau de Parfum"),
            ("Montblanc", "Legend Night"),
            ("Montblanc", "Legend Red"),
            ("Versace", "Eros Eau de Parfum"),
            ("Versace", "Eros Flame"),
            ("Armaf", "Club de Nuit Blue Iconic"),
        ]
    )
    assert match_offer(
        "Montblanc",
        "Legend Eau de Parfum",
        listing(
            title="Montblanc Legend Eau de Parfum Jumbo Spray - Men's Fragrance - "
            "Fougere Aromatic Woody - With notes of Bergamot, Jasmine & Oak Moss - 6.7 Fl Oz"
        ),
        identity_index=index,
    )
    assert match_offer(
        "Montblanc",
        "Legend Eau de Parfum",
        listing(title="Legend Eau de Parfum 100 ml Woody Aromatic Long Lasting"),
        identity_index=index,
    )
    for title in ["Legend Red EDP 100 ml", "Legend Night EDP 100 ml"]:
        assert (
            match_offer(
                "Montblanc", "Legend Eau de Parfum", listing(title=title), identity_index=index
            )
            is None
        )
    assert (
        match_offer(
            "Versace",
            "Eros Eau de Parfum",
            listing(title="Eros Flame EDP 100 ml"),
            identity_index=index,
        )
        is None
    )
    assert (
        match_offer(
            "Versace",
            "Eros Eau de Parfum",
            listing(title="Armaf Eros EDP 100 ml"),
            identity_index=index,
        )
        is None
    )
    assert (
        match_offer(
            "Versace",
            "Eros Eau de Parfum",
            listing(title="Eros EDP 100 ml by Armaf"),
            identity_index=index,
        )
        is None
    )


def test_catalog_descriptor_words_must_not_hide_a_named_flanker():
    from app.pricing.matching import IdentityIndex

    index = IdentityIndex([("Brand", "Scent Eau de Parfum"), ("Brand", "Scent Aromatic Woody")])
    assert (
        match_offer(
            "Brand",
            "Scent Eau de Parfum",
            listing(title="Scent Aromatic Woody EDP 100 ml"),
            identity_index=index,
        )
        is None
    )


def test_4711_splash_and_brand_alias():
    from app.pricing.matching import IdentityIndex

    index = IdentityIndex([("4711", "4711 Original Eau de Cologne")])
    for title in [
        "Original Eau De Cologne Splash 100ml",
        "Muelhens 4711 Original EDC Splash 100 ml",
    ]:
        assert match_offer(
            "4711", "4711 Original Eau de Cologne", listing(title=title), identity_index=index
        )


@pytest.mark.parametrize(
    "sizes,expected",
    [
        ([50, 100, 200], 100),
        ([50, 120, 200], 50),
        ([30, 50, 75, 200], 75),
        ([150, 200], 150),
        ([200], 200),
        ([97.6, 75, 200], 97.6),
    ],
)
def test_default_size_preference(sizes, expected):
    result = summary(tuple(price(size=size) for size in sizes), "Brand", "Name")
    assert result["best_offer"]["size_ml"] == expected


def test_no_amazon_offer_does_not_create_fallback_link():
    result = summary((), "Brand", "Name")
    assert result["offers"] == [] and result["best_offer"] is None
    assert result["search_links"] == {}


def test_catalog_shared_names_require_brand_context():
    from app.pricing.matching import IdentityIndex

    index = IdentityIndex([("Montblanc", "Legend Eau de Parfum"), ("Sapil", "Legend")])
    title = "Legend EDP 100 ml Woody Aromatic"
    assert (
        match_offer(
            "Montblanc",
            "Legend Eau de Parfum",
            listing(title=title, link="https://amazon.com/Sapil-Legend/dp/ASIN"),
            identity_index=index,
        )
        is None
    )
    assert (
        match_offer(
            "Montblanc",
            "Legend Eau de Parfum",
            listing(title=title, link="https://amazon.com/Liberty-LUXURY-Legend/dp/ASIN"),
            identity_index=index,
        )
        is None
    )
    assert match_offer(
        "Montblanc",
        "Legend Eau de Parfum",
        listing(title=title, link="https://amazon.com/Montblanc-Legend/dp/ASIN"),
        identity_index=index,
    )


def test_catalog_brand_named_scent_tolerates_description_but_not_other_named_perfume():
    from app.pricing.matching import IdentityIndex

    index = IdentityIndex([("Chloé", "Chloé Eau de Parfum"), ("Chloé", "Nomade")])
    assert match_offer(
        "Chloé",
        "Chloé Eau de Parfum",
        listing(title="Chloe EDP Spray 75 ml Long Lasting Floral"),
        identity_index=index,
    )
    assert (
        match_offer(
            "Chloé",
            "Chloé Eau de Parfum",
            listing(title="Chloe Nomade EDP Spray 75 ml Long Lasting Floral"),
            identity_index=index,
        )
        is None
    )
