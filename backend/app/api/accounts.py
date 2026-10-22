"""Every query is scoped to the authenticated user, never a client-supplied owner."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.auth.users import SESSION_COOKIE, current_user
from app.db.models import CollectionItem, Feedback, SavedFilter
from app.db.session import get_session

router = APIRouter(prefix="/me")


class ItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    perfume_id: int
    status: Literal["owned", "wishlist", "disliked"] = "owned"
    personal_rating: int | None = Field(default=None, ge=1, le=5)


class ItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["owned", "wishlist", "disliked"] | None = None
    personal_rating: int | None = Field(default=None, ge=1, le=5)


class ImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ItemInput] = Field(max_length=500)


class SavedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    filter_json: dict
    is_default: bool = False
    is_custom_row: bool = False


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    perfume_id: int
    action: Literal["not_interested", "clicked", "bought"]


def check_perfumes(ids):
    from app.api.routes import get_catalog

    try:
        get_catalog().rows(ids)
    except KeyError as exc:
        raise HTTPException(422, str(exc)) from exc


def item_json(item):
    return {
        "perfume_id": item.perfume_id,
        "status": item.status,
        "personal_rating": item.personal_rating,
        "added_at": item.added_at,
    }


async def find_item(session, user, pid):
    item = await session.scalar(
        select(CollectionItem).where(
            CollectionItem.user_id == user.id, CollectionItem.perfume_id == pid
        )
    )
    if item is None:
        raise HTTPException(404, "Collection item not found")
    return item


async def commit(session):
    try:
        await session.commit()
        from app.api.routes import cached_account_recommend

        cached_account_recommend.cache_clear()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "An item with that identity already exists") from exc


@router.get("/collection")
async def collection(user=Depends(current_user), session=Depends(get_session)):  # noqa: B008
    items = await session.scalars(
        select(CollectionItem)
        .where(CollectionItem.user_id == user.id)
        .order_by(CollectionItem.added_at)
    )
    return [item_json(i) for i in items]


@router.post("/collection", status_code=201)
async def add_item(
    body: ItemInput,
    user=Depends(current_user),  # noqa: B008
    session=Depends(get_session),  # noqa: B008
):  # noqa: B008
    check_perfumes([body.perfume_id])
    item = CollectionItem(user_id=user.id, **body.model_dump())
    session.add(item)
    await commit(session)
    return item_json(item)


@router.post("/collection/import")
async def import_collection(
    body: ImportInput,
    user=Depends(current_user),  # noqa: B008
    session=Depends(get_session),  # noqa: B008
):  # noqa: B008
    # Validate the entire batch before any changes, deduplicate, preserve existing edits.
    check_perfumes([i.perfume_id for i in body.items])
    existing = set(
        await session.scalars(
            select(CollectionItem.perfume_id).where(CollectionItem.user_id == user.id)
        )
    )
    added = 0
    for item in body.items:
        if item.perfume_id not in existing:
            session.add(CollectionItem(user_id=user.id, **item.model_dump()))
            existing.add(item.perfume_id)
            added += 1
    await commit(session)
    return {"imported": added}


@router.patch("/collection/{perfume_id}")
async def edit_item(
    perfume_id: int,
    body: ItemPatch,
    user=Depends(current_user),  # noqa: B008
    session=Depends(get_session),  # noqa: B008
):  # noqa: B008
    item = await find_item(session, user, perfume_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "status" and value is None:
            raise HTTPException(422, "Status cannot be null")
        setattr(item, key, value)
    await commit(session)
    return item_json(item)


@router.delete("/collection/{perfume_id}", status_code=204)
async def remove_item(
    perfume_id: int,
    user=Depends(current_user),  # noqa: B008
    session=Depends(get_session),  # noqa: B008
):  # noqa: B008
    await session.delete(await find_item(session, user, perfume_id))
    await commit(session)


@router.get("/filters")
async def filters(user=Depends(current_user), session=Depends(get_session)):  # noqa: B008
    return list(await session.scalars(select(SavedFilter).where(SavedFilter.user_id == user.id)))


@router.post("/filters", status_code=201)
async def save_filter(
    body: SavedInput,
    user=Depends(current_user),  # noqa: B008
    session=Depends(get_session),  # noqa: B008
):  # noqa: B008
    from pydantic import ValidationError

    from app.api.routes import FilterRequest

    try:
        validated = FilterRequest.model_validate(body.filter_json)
        # Validate note/accord names now rather than persisting unusable filters.
        from app.api.routes import get_catalog
        from app.engine.recommend import Filters, candidate_mask

        candidate_mask(get_catalog(), get_catalog().rows([]), Filters(**validated.model_dump()))
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if body.is_default:
        await session.execute(
            update(SavedFilter).where(SavedFilter.user_id == user.id).values(is_default=False)
        )
    saved = SavedFilter(
        user_id=user.id, **{**body.model_dump(), "filter_json": validated.model_dump(mode="json")}
    )
    session.add(saved)
    await commit(session)
    return saved


@router.delete("/filters/{filter_id}", status_code=204)
async def delete_filter(
    filter_id: uuid.UUID,
    user=Depends(current_user),  # noqa: B008
    session=Depends(get_session),  # noqa: B008
):  # noqa: B008
    saved = await session.scalar(
        select(SavedFilter).where(SavedFilter.id == filter_id, SavedFilter.user_id == user.id)
    )
    if saved is None:
        raise HTTPException(404, "Saved filter not found")
    await session.delete(saved)
    await commit(session)


@router.post("/feedback", status_code=201)
async def feedback(
    body: FeedbackInput,
    user=Depends(current_user),  # noqa: B008
    session=Depends(get_session),  # noqa: B008
):  # noqa: B008
    check_perfumes([body.perfume_id])
    existing = await session.scalar(
        select(Feedback).where(
            Feedback.user_id == user.id,
            Feedback.perfume_id == body.perfume_id,
            Feedback.action == body.action,
        )
    )
    if existing is None:
        session.add(Feedback(user_id=user.id, **body.model_dump()))
        await commit(session)
    return {"recorded": True}


@router.delete("", status_code=204)
async def delete_account(
    response: Response,
    user=Depends(current_user),  # noqa: B008
    session=Depends(get_session),  # noqa: B008
):  # noqa: B008
    # Database foreign keys cascade collections, filters, feedback, OAuth and sessions.
    await session.delete(user)
    await commit(session)
    response.delete_cookie(SESSION_COOKIE)


@router.get("/oauth")
async def connected_accounts(user=Depends(current_user)):  # noqa: B008
    return [
        {"provider": account.oauth_name, "email": account.account_email}
        for account in user.oauth_accounts
    ]
