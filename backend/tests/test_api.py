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
        {"filters": {"price_max": 60}},
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
