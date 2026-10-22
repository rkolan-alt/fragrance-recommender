"""Public catalog and guest recommendations. Account routes arrive in milestone 6."""

import json
from dataclasses import asdict
from functools import lru_cache
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from rapidfuzz import fuzz, process
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.auth.users import optional_user
from app.config import settings
from app.db.models import CollectionItem, Feedback, SavedFilter
from app.db.session import get_session
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
    owned_ids: list[int] | None = Field(default=None, min_length=5, max_length=500)
    filters: FilterRequest | None = None
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


@lru_cache(maxsize=128)
def cached_account_recommend(
    user_id: str, state: tuple, hidden: tuple[int, ...], filters: FilterRequest, limit: int
):
    owned = [pid for pid, status, _ in state if status == "owned"]
    ratings = {
        pid: rating for pid, status, rating in state if status == "owned" and rating is not None
    }
    disliked = tuple(pid for pid, status, _ in state if status == "disliked")
    excluded = tuple(sorted(set(hidden) | {pid for pid, status, _ in state if status != "owned"}))
    return recommend_rows(
        get_catalog(),
        owned,
        Filters(**filters.model_dump()),
        limit,
        ratings=ratings,
        disliked_ids=disliked,
        excluded_ids=excluded,
    )


@router.post("/recommend")
async def recommendations(
    body: RecommendRequest,
    user=Depends(optional_user),  # noqa: B008
    session=Depends(get_session),  # noqa: B008
):  # noqa: B008
    try:
        if user is None:
            if body.owned_ids is None or len(set(body.owned_ids)) < 5:
                raise HTTPException(422, "Add at least five distinct owned fragrances")
            rows = await run_in_threadpool(
                cached_recommend,
                tuple(sorted(set(body.owned_ids))),
                body.filters or FilterRequest(),
                body.limit,
            )
        else:
            if body.owned_ids is not None:
                raise HTTPException(422, "Signed-in recommendations use your saved collection")
            items = list(
                await session.scalars(
                    select(CollectionItem).where(CollectionItem.user_id == user.id)
                )
            )
            state = tuple(sorted((i.perfume_id, i.status, i.personal_rating) for i in items))
            hidden = tuple(
                sorted(
                    await session.scalars(
                        select(Feedback.perfume_id).where(
                            Feedback.user_id == user.id, Feedback.action == "not_interested"
                        )
                    )
                )
            )
            saved = list(
                await session.scalars(
                    select(SavedFilter)
                    .where(SavedFilter.user_id == user.id)
                    .order_by(SavedFilter.name)
                )
            )
            default = next((f.filter_json for f in saved if f.is_default), {})
            filters = body.filters or FilterRequest.model_validate(default)
            rows = list(
                await run_in_threadpool(
                    cached_account_recommend, str(user.id), state, hidden, filters, body.limit
                )
            )
            from app.engine.categories import CategoryRow

            for custom in saved:
                if custom.is_custom_row:
                    custom_rows = await run_in_threadpool(
                        cached_account_recommend,
                        str(user.id),
                        state,
                        hidden,
                        FilterRequest.model_validate(custom.filter_json),
                        body.limit,
                    )
                    rows.append(
                        CategoryRow(f"custom_{custom.id}", custom.name, custom_rows[0].items)
                    )
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
