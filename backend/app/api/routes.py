"""Public catalog and guest recommendations. Account routes arrive in milestone 6."""

import json
from dataclasses import asdict
from functools import lru_cache
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from rapidfuzz import fuzz, process

from app.config import settings
from app.engine.catalog import load_catalog
from app.engine.categories import recommend_rows
from app.engine.recommend import Filters

router = APIRouter()


@lru_cache(maxsize=1)
def get_catalog():
    try:
        return load_catalog()
    except FileNotFoundError as exc:
        raise HTTPException(503, "Catalog unavailable; build the data artifacts first") from exc


@lru_cache(maxsize=1)
def get_details():
    try:
        return pd.read_parquet(settings.data_dir / "processed" / "perfumes.parquet")
    except FileNotFoundError as exc:
        raise HTTPException(503, "Catalog details unavailable") from exc


class FilterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    genders: tuple[Literal["male", "female", "unisex"], ...] = ()
    seasons: tuple[Literal["winter", "spring", "summer", "autumn"], ...] = ()
    min_season_share: float = Field(default=0.5, ge=0, le=1)
    min_rating: float | None = Field(default=None, ge=0, le=5)
    min_votes: int | None = Field(default=None, ge=0)
    min_longevity: float | None = Field(default=None, ge=1, le=5)
    max_longevity: float | None = Field(default=None, ge=1, le=5)
    include_accords: tuple[str, ...] = Field(default=(), max_length=100)
    exclude_accords: tuple[str, ...] = Field(default=(), max_length=100)
    include_notes: tuple[str, ...] = Field(default=(), max_length=100)
    exclude_notes: tuple[str, ...] = Field(default=(), max_length=100)
    exclude_brands: tuple[str, ...] = Field(default=(), max_length=100)
    include_clones: bool = False

    @model_validator(mode="after")
    def valid_range(self):
        if (
            self.min_longevity is not None
            and self.max_longevity is not None
            and self.min_longevity > self.max_longevity
        ):
            raise ValueError("minimum longevity exceeds maximum")
        return self


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owned_ids: list[int] = Field(min_length=5, max_length=500)
    filters: FilterRequest = Field(default_factory=FilterRequest)
    categories: list[str] | None = Field(default=None, max_length=20)
    limit: int = Field(default=20, ge=1, le=50)


@lru_cache(maxsize=1)
def search_names():
    p = get_catalog().perfumes
    return (p.brand + " " + p.name).str.casefold().tolist()


@router.get("/search")
def search(
    q: str = Query(min_length=1, max_length=200), limit: int = Query(default=10, ge=1, le=50)
):
    q = q.strip().casefold()
    if not q:
        return []
    p = get_catalog().perfumes
    matches = process.extract(q, search_names(), scorer=fuzz.WRatio, limit=limit, score_cutoff=55)
    return [
        {
            "id": int(p.at[i, "id"]),
            "name": p.at[i, "name"],
            "brand": p.at[i, "brand"],
            "year": None if pd.isna(p.at[i, "year"]) else int(p.at[i, "year"]),
        }
        for _, _, i in matches
    ]


@lru_cache(maxsize=128)
def cached_recommend(owned: tuple[int, ...], filters: FilterRequest, limit: int):
    return recommend_rows(get_catalog(), list(owned), Filters(**filters.model_dump()), limit)


@router.post("/recommend")
def recommendations(body: RecommendRequest):
    if len(set(body.owned_ids)) < 5:
        raise HTTPException(422, "Add at least five distinct owned fragrances")
    try:
        rows = cached_recommend(tuple(sorted(set(body.owned_ids))), body.filters, body.limit)
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if body.categories is not None:
        unknown = set(body.categories) - {r.key for r in rows}
        if unknown:
            raise HTTPException(422, f"Unknown categories: {sorted(unknown)}")
        rows = [r for r in rows if r.key in body.categories]
    ids = {item.id for row in rows for item in row.items}
    details = get_details()
    columns = [
        c
        for c in (
            "id",
            "gender",
            "rating_avg",
            "vote_count",
            "accords",
            "longevity_avg",
            "season_share_winter",
            "season_share_spring",
            "season_share_summer",
            "season_share_autumn",
        )
        if c in details.columns
    ]
    records = json.loads(details.loc[details.id.isin(ids), columns].to_json(orient="records"))
    metadata = {record["id"]: record for record in records}
    return {
        "rows": [
            {
                "key": row.key,
                "title": row.title,
                "subtitle": f"{len(row.items)} recommendations",
                "items": [{**metadata.get(item.id, {}), **asdict(item)} for item in row.items],
            }
            for row in rows
        ]
    }


@router.get("/perfume/{perfume_id}")
def perfume_detail(perfume_id: int):
    catalog = get_catalog()
    if perfume_id not in catalog.row_of:
        raise HTTPException(404, "Perfume not found")
    details = get_details()
    row = details[details.id == perfume_id]
    if row.empty:
        raise HTTPException(404, "Perfume details not found")
    # pandas JSON converts numpy arrays and missing numeric values safely.
    result = json.loads(row.to_json(orient="records"))[0]
    allowed = {
        "id",
        "name",
        "brand",
        "year",
        "url",
        "gender",
        "rating_avg",
        "vote_count",
        "accords",
        "notes_top",
        "notes_middle",
        "notes_base",
        "longevity_avg",
        "longevity_votes",
        *(f"longevity_b{i}" for i in range(1, 6)),
        *(f"season_share_{s}" for s in ("winter", "spring", "summer", "autumn")),
    }
    result = {k: v for k, v in result.items() if k in allowed}
    result["offers"] = []  # populated by the pricing service in milestone 7
    return result
