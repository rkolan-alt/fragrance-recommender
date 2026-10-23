import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from tests.test_engine import make_catalog, perfume


@pytest.fixture
def client(monkeypatch):
    catalog = make_catalog(*(perfume(i) for i in range(1, 9)))
    monkeypatch.setattr(routes, "get_catalog", lambda: catalog)
    monkeypatch.setattr(routes, "get_details", lambda: catalog.perfumes)

    async def no_prices(session):
        return ()

    monkeypatch.setattr(routes, "load_prices", no_prices)
    routes.search_names.cache_clear()
    routes.cached_recommend.cache_clear()
    yield TestClient(app)
    routes.search_names.cache_clear()
    routes.cached_recommend.cache_clear()


def test_search_and_details(client):
    data = client.get("/search", params={"q": "Brand 1 Perfume 1"}).json()
    assert data[0]["id"] == 1
    assert client.get("/perfume/1").json()["id"] == 1
    assert client.get("/perfume/999999").status_code == 404


def test_recommend_and_category_selection(client):
    body = {"owned_ids": [1, 2, 3, 4, 5], "categories": ["for_you"]}
    response = client.post("/recommend", json=body)
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert [r["key"] for r in rows] == ["for_you"]
    assert not {i["id"] for i in rows[0]["items"]} & set(body["owned_ids"])
    body["filters"] = {"min_votes": 10**9}
    assert client.post("/recommend", json=body).json()["rows"][0]["items"] == []


@pytest.mark.parametrize(
    "update",
    [
        {"owned_ids": [1, 2]},
        {"owned_ids": [1] * 5},
        {"owned_ids": [1, 2, 3, 4, 99999]},
        {"filters": {"genders": ["invalid"]}},
        {"filters": {"min_rating": 6}},
        {"filters": {"min_longevity": 5, "max_longevity": 2}},
        {"filters": {"include_notes": ["nonexistent note"]}},
        {"filters": {"price_max": -1}},
        {"categories": ["does_not_exist"]},
        {"limit": 0},
    ],
)
def test_invalid_requests(client, update):
    body = {"owned_ids": [1, 2, 3, 4, 5], **update}
    assert client.post("/recommend", json=body).status_code == 422


def test_missing_detail_values_are_json_null(client, monkeypatch):
    monkeypatch.setattr(
        routes,
        "get_details",
        lambda: pd.DataFrame(
            [{"id": 1, "year": float("nan"), "notes_top": [{"name": "musk", "weight": 50}]}]
        ),
    )
    result = client.get("/perfume/1").json()
    assert result["year"] is None
    assert result["notes_top"][0]["name"] == "musk"


def test_budget_store_filters_and_price_changes_invalidate_cache(client, monkeypatch):
    from tests.test_pricing import price

    snapshot = [
        price(amount="50", pid=6),
        price("amazon", "55", pid=6),
        price(amount="80", pid=7),
        price(amount="40", pid=8),
    ]

    async def prices(session):
        return tuple(snapshot)

    monkeypatch.setattr(routes, "load_prices", prices)
    body = {"owned_ids": [1, 2, 3, 4, 5], "categories": ["budget"]}
    response = client.post("/recommend", json=body)
    assert response.status_code == 200
    items = response.json()["rows"][0]["items"]
    assert {i["id"] for i in items} == {6, 8}
    assert all(i["best_offer"]["price"] <= 60 for i in items)
    body["filters"] = {"store": "amazon", "price_min": 45, "price_max": 60}
    items = client.post("/recommend", json=body).json()["rows"][0]["items"]
    assert [i["id"] for i in items] == [6]
    assert items[0]["best_offer"]["store"] == "amazon"
    snapshot[:] = [price("amazon", "90", pid=6)]
    assert client.post("/recommend", json=body).json()["rows"][0]["items"] == []


def test_details_without_prices_have_no_purchase_links(client):
    result = client.get("/perfume/1").json()
    assert result["search_links"] == {}
    assert result["offers"] == [] and result["best_offer"] is None


@pytest.mark.parametrize(
    "filters",
    [
        {"price_min": 100, "price_max": 10},
        {"store": "unknown"},
        {"store": "jomashop"},
        {"budget_max": 0},
    ],
)
def test_invalid_price_filters(client, filters):
    assert (
        client.post(
            "/recommend", json={"owned_ids": [1, 2, 3, 4, 5], "filters": filters}
        ).status_code
        == 422
    )


def test_images_appear_in_search_recommendations_and_details(client, monkeypatch):
    monkeypatch.setattr(
        routes, "get_image_url", lambda pid: f"https://fimgs.net/mdimg/perfume/375x500.{pid}.jpg"
    )
    matches = client.get("/search", params={"q": "Brand 1 Perfume 1"}).json()
    assert matches[0]["image_url"].endswith(".1.jpg")
    response = client.post(
        "/recommend", json={"owned_ids": [1, 2, 3, 4, 5], "categories": ["for_you"]}
    )
    items = response.json()["rows"][0]["items"]
    assert items and all(i["image_url"].endswith(f".{i['id']}.jpg") for i in items)
    assert client.get("/perfume/1").json()["image_url"].endswith(".1.jpg")


@pytest.mark.parametrize(
    "query",
    [
        "angels share",
        "Angels’ Share",
        "angel's share",
        "angel share",
        "angels",
        "By Kilian Angels' Share",
    ],
)
def test_fragrance_name_matches_are_not_buried_by_unrelated_fuzzy_results(
    client, monkeypatch, query
):
    catalog = make_catalog(
        *(
            perfume(100 + i, brand="Victoria's Secret", name=f"Dream Angels Heavenly {i}")
            for i in range(25)
        ),
        perfume(62615, brand="By Kilian", name="Angels' Share", vote_count=23000),
        perfume(101629, brand="By Kilian", name="Angels' Share Paradis"),
        perfume(113083, brand="By Kilian", name="Angels' Share On The Rocks"),
    )
    monkeypatch.setattr(routes, "get_catalog", lambda: catalog)
    routes.search_names.cache_clear()
    data = client.get("/search", params={"q": query}).json()
    assert data[0]["id"] == 62615
    if query in ["angels share", "Angels’ Share", "angels"]:
        assert {62615, 101629, 113083} <= {item["id"] for item in data[:3]}


def test_search_handles_accents_and_punctuation_only_input(client, monkeypatch):
    catalog = make_catalog(perfume(1733, brand="Chloé", name="Chloé Eau de Parfum"))
    monkeypatch.setattr(routes, "get_catalog", lambda: catalog)
    routes.search_names.cache_clear()
    assert client.get("/search", params={"q": "Chloe eau de parfum"}).json()[0]["id"] == 1733
    assert client.get("/search", params={"q": "'' --"}).json() == []
