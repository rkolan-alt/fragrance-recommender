from app.engine.categories import recommend_rows
from app.engine.recommend import Filters
from app.pricing.discovery import price_candidates
from app.pricing.matching import IdentityIndex, match_offer, match_product_link
from app.pricing.service import summary
from tests.test_accounts import account_app  # noqa: F401
from tests.test_engine import CITRUS, GOURMAND, make_catalog, perfume
from tests.test_pricing import listing, price


def test_value_price_discovery_is_personalized_and_respects_clone_ownership_exclusions():
    catalog = make_catalog(
        *(perfume(i, CITRUS if i <= 5 else GOURMAND) for i in range(1, 11)),
        perfume(20, CITRUS, brand="Lattafa Perfumes"),
        perfume(21, GOURMAND, brand="Afnan"),
        perfume(22, CITRUS, brand="Rasasi", is_clone=True),
        perfume(23, CITRUS, brand="Armaf"),
    )
    fresh = price_candidates(catalog, [1, 2, 3, 4, 5], priced_ids=[23], limit=1)
    sweet = price_candidates(catalog, [6, 7, 8, 9, 10], priced_ids=[23], limit=1)
    assert fresh[0][0] == 20 and sweet[0][0] == 21
    assert 22 not in [p[0] for p in price_candidates(catalog, [1, 2, 3, 4, 5])]
    assert 22 in [
        p[0] for p in price_candidates(catalog, [1, 2, 3, 4, 5], Filters(include_clones=True))
    ]
    assert 20 not in [p[0] for p in price_candidates(catalog, [1, 2, 3, 4, 5], excluded_ids=[20])]


def test_budget_does_not_fill_sparse_pool_with_unrelated_bottles():
    catalog = make_catalog(
        *(perfume(i, CITRUS if i <= 5 else GOURMAND) for i in range(1, 11)),
        *(perfume(i, CITRUS) for i in range(30, 45)),
        perfume(20, CITRUS, brand="Lattafa Perfumes"),
        perfume(21, GOURMAND, brand="Afnan"),
    )
    offers = (price(pid=20), price(pid=21))
    fresh = next(
        r for r in recommend_rows(catalog, [1, 2, 3, 4, 5], prices=offers) if r.key == "budget"
    )
    sweet = next(
        r for r in recommend_rows(catalog, [6, 7, 8, 9, 10], prices=offers) if r.key == "budget"
    )
    assert [r.id for r in fresh.items] == [20]
    assert [r.id for r in sweet.items] == [21]


def test_listing_concentration_can_identify_unqualified_catalog_entry():
    index = IdentityIndex(
        [
            ("Creed", "Aventus"),
            ("Creed", "Aventus Cologne"),
            ("Dior", "Sauvage"),
            ("Dior", "Sauvage Eau de Parfum"),
        ]
    )
    assert match_offer(
        "Creed", "Aventus", listing(title="Creed Aventus EDP 100 ml"), identity_index=index
    )
    assert (
        match_offer(
            "Creed",
            "Aventus",
            listing(title="Creed Aventus Cologne EDP 100 ml"),
            identity_index=index,
        )
        is None
    )
    assert (
        match_offer(
            "Dior", "Sauvage", listing(title="Dior Sauvage EDP 100 ml"), identity_index=index
        )
        is None
    )


def test_aventus_can_have_a_product_link_without_inventing_price_or_size():
    index = IdentityIndex([("Creed", "Aventus"), ("Creed", "Aventus Cologne")])
    raw = listing(
        title="Aventus, Men's Luxury Cologne, Dry Woods, Fresh & Citrus Fruity Fragrance",
        link="https://www.amazon.com/Creed-Aventus/dp/B071CYS5ZZ/",
    )
    assert match_offer("Creed", "Aventus", raw, identity_index=index) is None
    link = match_product_link("Creed", "Aventus", raw, identity_index=index)
    assert link and link.url == raw["link"]
    data = summary((), "Creed", "Aventus", product_link={"url": link.url, "title": link.title})
    assert data["amazon_link"]["url"] == raw["link"]
    assert data["best_offer"] is None and data["price_status"] == "link_only"
    raw["title"] = "Aventus Cologne – Men’s Luxury Cologne"
    assert match_product_link("Creed", "Aventus", raw, identity_index=index) is None


def test_value_matching_rejects_multipacks_bundles_and_wrong_gender():
    index = IdentityIndex(
        [
            ("Rasasi", "Daarej pour Homme"),
            ("Rasasi", "Daarej pour Femme"),
            ("Rasasi", "Hawas for Him"),
        ]
    )
    assert match_offer(
        "Rasasi",
        "Daarej pour Homme",
        listing(title="Rasasi Daarej for Men EDP 100 ml"),
        identity_index=index,
    )
    for title in [
        "Rasasi Daarej for Men EDP 100 ml (Pack of 4)",
        "Daarej Verve for Men - 3.38 oz EDP Spray",
        "Hawas For Him & Daarej For Homme EDP 100Ml (3.4Oz)",
        "Rasasi Hawas EDP and Daarej for Men EDP Bundle 100 ml Each",
        "Rasasi Daarej for Women EDP 100 ml",
    ]:
        assert (
            match_offer("Rasasi", "Daarej pour Homme", listing(title=title), identity_index=index)
            is None
        )


def test_link_only_refresh_is_persisted_but_never_counts_as_a_budget_price(account_app):  # noqa: F811
    import asyncio
    from datetime import UTC, datetime, timedelta

    from app.db.models import ProductLink
    from app.pricing.service import load_prices, load_product_links, refresh_one

    index = IdentityIndex([("Creed", "Aventus")])

    class Client:
        async def search(self, brand, name):
            return [
                listing(
                    title="Creed Aventus Men's Luxury Cologne",
                    link="https://www.amazon.com/Creed-Aventus/dp/B071CYS5ZZ/",
                )
            ]

    _, factory = account_app

    async def run():
        assert (
            await refresh_one(
                9828, "Creed", "Aventus", factory=factory, client=Client(), identity_index=index
            )
            == "link_only"
        )
        async with factory() as session:
            assert await load_prices(session) == ()
            assert (await load_product_links(session))[9828]["url"].endswith("B071CYS5ZZ/")
            record = await session.get(ProductLink, 9828)
            record.fetched_at = datetime.now(UTC) - timedelta(days=8)
            await session.commit()
            assert await load_product_links(session) == {}

    asyncio.run(run())


def test_budget_leads_with_priced_value_houses_but_never_assumes_a_brand_is_cheap():
    catalog = make_catalog(
        *(perfume(i) for i in range(1, 6)),
        perfume(20, brand="Versace", rating_avg=4.7, vote_count=50000),
        perfume(21, brand="Lattafa Perfumes"),
        perfume(22, brand="Afnan"),
        perfume(23, brand="Swiss Arabian"),
    )
    offers = (price(pid=20), price(pid=21, amount="25"), price(pid=22, amount="90"))
    row = next(
        row
        for row in recommend_rows(catalog, [1, 2, 3, 4, 5], prices=offers)
        if row.key == "budget"
    )
    assert [item.id for item in row.items] == [21, 20]


def test_direct_link_does_not_accept_a_mixed_concentration_bundle():
    index = IdentityIndex([("Versace", "Eros Eau de Parfum")])
    assert (
        match_product_link(
            "Versace",
            "Eros Eau de Parfum",
            listing(
                title="Versace Eros Eau de Parfum 100 ml & Eros Eau de Toilette 100 ml",
                link="https://www.amazon.com/Versace-Eros/dp/B071CYS5ZZ/",
            ),
            identity_index=index,
        )
        is None
    )
