"""Public catalog and guest recommendations. Account routes arrive in milestone 6."""

import json
import re
import unicodedata
from dataclasses import asdict
from functools import lru_cache
from typing import Literal

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
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
from app.images import get_image_url
from app.pricing.discovery import price_candidates
from app.pricing.service import due_items, load_prices, load_product_links, refresh_batch, summary

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
    price_min: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    price_max: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    store: Literal["any", "amazon"] = "any"
    budget_max: float = Field(default=60, gt=0, le=10000, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_range(self):
        if (
            self.price_min is not None
            and self.price_max is not None
            and self.price_min > self.price_max
        ):
            raise ValueError("minimum price exceeds maximum")
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


def normalize_search(value):
    text = unicodedata.normalize("NFKD", value).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"['’‘`ʼ]", "", text)
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


@lru_cache(maxsize=1)
def search_names():
    p = get_catalog().perfumes
    return (
        [normalize_search(name) for name in p.name],
        [normalize_search(f"{brand} {name}") for brand, name in zip(p.brand, p.name, strict=True)],
    )


@router.get("/search")
def search(
    q: str = Query(min_length=1, max_length=200), limit: int = Query(default=10, ge=1, le=50)
):
    q = normalize_search(q)
    if not q:
        return []
    p = get_catalog().perfumes
    names, labels = search_names()
    # Find literal matches across the whole catalog before truncating suggestions.
    # Fuzzy name matches also prevent long brand labels from drowning out a scent.
    candidates = {i for i, label in enumerate(labels) if q in label}
    for values in (names, labels):
        candidates.update(
            i
            for _, _, i in process.extract(
                q, values, scorer=fuzz.WRatio, limit=max(100, limit), score_cutoff=55
            )
        )

    def key(i):
        name, label = names[i], labels[i]
        tier = (
            0
            if name == q
            else 1
            if name.startswith(q)
            else 2
            if q in name
            else 3
            if q in label
            else 4
        )
        score = max(fuzz.WRatio(q, name), 0.95 * fuzz.WRatio(q, label))
        return (tier, -score, -fuzz.ratio(q, name), -int(p.at[i, "vote_count"]), i)

    matches = sorted(candidates, key=key)[:limit]
    return [
        {
            "id": int(p.at[i, "id"]),
            "image_url": get_image_url(int(p.at[i, "id"])),
            "name": p.at[i, "name"],
            "brand": p.at[i, "brand"],
            "year": None if pd.isna(p.at[i, "year"]) else int(p.at[i, "year"]),
        }
        for i in matches
    ]


@lru_cache(maxsize=128)
def cached_recommend(owned: tuple[int, ...], filters: FilterRequest, limit: int, prices=()):
    return recommend_rows(
        get_catalog(), list(owned), Filters(**filters.model_dump()), limit, prices=prices
    )


@lru_cache(maxsize=128)
def cached_account_recommend(
    user_id: str,
    state: tuple,
    hidden: tuple[int, ...],
    filters: FilterRequest,
    limit: int,
    prices=(),
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
        prices=prices,
    )


@router.post("/recommend")
async def recommendations(
    body: RecommendRequest,
    background_tasks: BackgroundTasks,
    user=Depends(optional_user),  # noqa: B008
    session=Depends(get_session),  # noqa: B008
):  # noqa: B008
    prices = await load_prices(session)
    product_links = await load_product_links(session)
    response_filters = body.filters or FilterRequest()
    row_filters = {}
    discovery_ratings = None
    discovery_disliked = ()
    discovery_excluded = ()
    try:
        if user is None:
            if body.owned_ids is None or len(set(body.owned_ids)) < 5:
                raise HTTPException(422, "Add at least five distinct owned fragrances")
            discovery_owned = list(sorted(set(body.owned_ids)))
            rows = await run_in_threadpool(
                cached_recommend,
                tuple(sorted(set(body.owned_ids))),
                body.filters or FilterRequest(),
                body.limit,
                prices,
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
            discovery_owned = [pid for pid, status, _ in state if status == "owned"]
            discovery_ratings = {
                pid: rating
                for pid, status, rating in state
                if status == "owned" and rating is not None
            }
            discovery_disliked = tuple(pid for pid, status, _ in state if status == "disliked")
            discovery_excluded = tuple(
                set(hidden) | {pid for pid, status, _ in state if status != "owned"}
            )
            default = next((f.filter_json for f in saved if f.is_default), {})
            filters = body.filters or FilterRequest.model_validate(default)
            response_filters = filters
            rows = list(
                await run_in_threadpool(
                    cached_account_recommend,
                    str(user.id),
                    state,
                    hidden,
                    filters,
                    body.limit,
                    prices,
                )
            )
            from app.engine.categories import CategoryRow

            for custom in saved:
                if custom.is_custom_row:
                    row_filters[f"custom_{custom.id}"] = FilterRequest.model_validate(
                        custom.filter_json
                    )
                    custom_rows = await run_in_threadpool(
                        cached_account_recommend,
                        str(user.id),
                        state,
                        hidden,
                        FilterRequest.model_validate(custom.filter_json),
                        body.limit,
                        prices,
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
    by_id = {}
    for offer in prices:
        by_id.setdefault(offer.perfume_id, []).append(offer)

    checking_ids = set()

    def priced_card(item, key):
        active_filters = row_filters.get(key, response_filters)
        cap = active_filters.price_max
        if key == "budget":
            cap = (
                min(cap, active_filters.budget_max)
                if cap is not None
                else active_filters.budget_max
            )
        pricing = summary(
            by_id.get(item.id, ()),
            item.brand,
            item.name,
            price_min=active_filters.price_min,
            price_max=cap,
            store=active_filters.store,
            product_link=product_links.get(item.id),
        )
        if item.id in checking_ids and pricing["best_offer"] is None:
            pricing["price_status"] = "checking"
        return {
            **metadata.get(item.id, {}),
            **asdict(item),
            "image_url": get_image_url(item.id),
            **pricing,
        }

    if settings.pricing_auto_refresh and settings.serpapi_key:
        candidates = get_catalog().perfumes
        pending = [
            (
                pid,
                candidates.at[get_catalog().row_of[pid], "brand"],
                candidates.at[get_catalog().row_of[pid], "name"],
            )
            for pid in sorted(ids)
            if pid not in by_id
        ]
        value_candidates = await run_in_threadpool(
            price_candidates,
            get_catalog(),
            discovery_owned,
            Filters(**response_filters.model_dump()),
            ratings=discovery_ratings,
            disliked_ids=discovery_disliked,
            excluded_ids=discovery_excluded,
            priced_ids=tuple(by_id),
        )
        # Unknown value candidates must be considered even when they cannot yet
        # appear in the price-gated Budget row. Alternate with normal card lookups.
        combined = []
        for i in range(max(len(value_candidates), len(pending))):
            if i < len(value_candidates):
                combined.append(value_candidates[i])
            if i < len(pending):
                combined.append(pending[i])
        seen = set()
        combined = [item for item in combined if not (item[0] in seen or seen.add(item[0]))]
        pending = await due_items(session, combined)
        checking_ids = {pid for pid, _, _ in pending}
        background_tasks.add_task(refresh_batch, pending)
    return {
        "rows": [
            {
                "key": row.key,
                "title": row.title,
                "subtitle": f"{len(row.items)} recommendations",
                "items": [priced_card(item, row.key) for item in row.items],
            }
            for row in rows
        ]
    }


@router.get("/perfume/{perfume_id}")
async def perfume_detail(
    perfume_id: int,
    background_tasks: BackgroundTasks,
    session=Depends(get_session),  # noqa: B008
):  # noqa: B008
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
    prices = tuple(o for o in await load_prices(session) if o.perfume_id == perfume_id)
    meta = catalog.perfumes.loc[catalog.row_of[perfume_id]]
    result["image_url"] = get_image_url(perfume_id)
    links = await load_product_links(session)
    result.update(summary(prices, meta.brand, meta["name"], product_link=links.get(perfume_id)))
    if not prices and settings.pricing_auto_refresh and settings.serpapi_key:
        pending = await due_items(session, [(perfume_id, meta.brand, meta["name"])])
        if pending:
            result["price_status"] = "checking"
            background_tasks.add_task(refresh_batch, pending)
    return result
