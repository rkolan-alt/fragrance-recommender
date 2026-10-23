"""Fresh offer snapshots, database refresh leases and a shared daily query cap."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.models import Offer, PriceRefresh, PricingQuota
from app.db.session import session_factory
from app.pricing.client import PricingError, PricingQuotaError, SerpApiClient
from app.pricing.matching import get_identity_index, match_offer


@dataclass(frozen=True)
class Price:
    perfume_id: int
    store: str
    price: Decimal
    size_ml: float
    concentration: str
    url: str
    title: str
    fetched_at: str

    def public(self):
        return {
            **asdict(self),
            "price": float(self.price),
            "currency": "USD",
            "price_per_ml": round(float(self.price) / self.size_ml, 4),
        }


async def load_prices(session) -> tuple[Price, ...]:
    cutoff = datetime.now(UTC) - timedelta(days=settings.pricing_cache_days)
    offers = await session.scalars(
        select(Offer)
        .where(Offer.fetched_at >= cutoff, Offer.store == "amazon")
        .order_by(Offer.perfume_id, Offer.store, Offer.url, Offer.id)
    )
    return tuple(
        Price(
            o.perfume_id,
            o.store,
            o.price,
            o.size_ml,
            o.concentration,
            o.url,
            o.title,
            (
                o.fetched_at.replace(tzinfo=UTC) if o.fetched_at.tzinfo is None else o.fetched_at
            ).isoformat(),
        )
        for o in offers
    )


def eligible(prices, *, price_min=None, price_max=None, store="any"):
    return tuple(
        p
        for p in prices
        if p.store == "amazon"
        and (store == "any" or p.store == store)
        and (price_min is None or p.price >= Decimal(str(price_min)))
        and (price_max is None or p.price <= Decimal(str(price_max)))
    )


def summary(prices, brand, name, *, price_min=None, price_max=None, store="any"):
    prices = eligible(prices, price_min=price_min, price_max=price_max, store=store)
    groups = {}
    for p in prices:
        # Retail fl-oz rounding: 3.3/3.4 oz and 100 ml share a nominal size group.
        groups.setdefault((p.concentration, round(p.size_ml / 5) * 5), []).append(p)
    best = None
    if groups:
        group = min(
            groups.values(),
            key=lambda g: (
                0 if round(g[0].size_ml / 5) * 5 == 100 else 1 if g[0].size_ml < 100 else 2,
                abs(g[0].size_ml - 100),
                g[0].concentration,
            ),
        )
        best = min(group, key=lambda p: (p.price, p.store, p.url))
    value = min(prices, key=lambda p: float(p.price) / p.size_ml) if prices else None
    return {
        "offers": [p.public() for p in prices],
        "best_offer": best.public() if best else None,
        "best_value_offer": value.public() if value else None,
        "price_status": "cached" if prices else "unavailable",
        "pricing_source": "amazon",
        "price_label": "Best matched Amazon offer",
        "price_basis": (
            "100 ml first, then smaller sizes descending, then larger sizes ascending; "
            "shipping and tax excluded"
        ),
        "search_links": {},
    }


async def _claim(session, pid, now, retry_completed=False):
    row = await session.get(PriceRefresh, pid)
    if row is None:
        session.add(
            PriceRefresh(
                perfume_id=pid, state="checking", next_refresh_at=now + timedelta(minutes=5)
            )
        )
        try:
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False
    result = await session.execute(
        update(PriceRefresh)
        .where(
            PriceRefresh.perfume_id == pid,
            or_(
                PriceRefresh.next_refresh_at <= now,
                PriceRefresh.state.in_(["ready", "no_match"]) if retry_completed else False,
            ),
        )
        .execution_options(synchronize_session=False)
        .values(state="checking", next_refresh_at=now + timedelta(minutes=5))
    )
    await session.commit()
    return result.rowcount == 1


async def _consume_quota(session, now):
    day = now.date().isoformat()
    if await session.get(PricingQuota, day) is None:
        session.add(PricingQuota(day=day, requests=0))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
    result = await session.execute(
        update(PricingQuota)
        .where(
            PricingQuota.day == day, PricingQuota.requests < settings.pricing_daily_request_limit
        )
        .values(requests=PricingQuota.requests + 1)
    )
    await session.commit()
    return result.rowcount == 1


async def refresh_one(
    pid: int,
    brand: str,
    name: str,
    *,
    factory=None,
    client=None,
    response_sink=None,
    retry_completed=False,
    identity_index=None,
):
    if client is None and not settings.serpapi_key:
        return "not_configured"
    # Unknown concentration is intentionally not guessed or sent as a paid query.
    from app.pricing.matching import concentration

    if concentration(name) is None:
        return "ambiguous_variant"
    now = datetime.now(UTC)
    async with (factory or session_factory)() as session:
        if not await _claim(session, pid, now, retry_completed):
            return "cached_or_pending"
        if client is not None and not await _consume_quota(session, now):
            await session.execute(
                update(PriceRefresh)
                .where(PriceRefresh.perfume_id == pid)
                .values(state="quota_limited", next_refresh_at=now + timedelta(hours=1))
            )
            await session.commit()
            return "quota_limited"
        try:

            async def reserve():
                return await _consume_quota(session, datetime.now(UTC))

            provider = client or SerpApiClient(
                settings.serpapi_key,
                reserve=reserve,
                response_sink=response_sink,
            )
            results = await provider.search(brand, name)
            index = identity_index
            if index is None and client is None:
                index = get_identity_index()
            matched = {
                m.url: m
                for r in results
                if (m := match_offer(brand, name, r, identity_index=index)) is not None
            }
        except PricingQuotaError:
            await session.execute(
                update(PriceRefresh)
                .where(PriceRefresh.perfume_id == pid)
                .values(state="quota_limited", next_refresh_at=now + timedelta(hours=1))
            )
            await session.commit()
            return "quota_limited"
        except PricingError:
            await session.execute(
                update(PriceRefresh)
                .where(PriceRefresh.perfume_id == pid)
                .values(state="error", next_refresh_at=now + timedelta(hours=6))
            )
            await session.commit()
            return "error"
        return await store_matches(session, pid, list(matched.values()), now)


async def store_matches(session, pid, matched, now):
    """Persist one successful, already-quota-counted observation atomically."""
    await session.execute(delete(Offer).where(Offer.perfume_id == pid))
    for m in matched:
        session.add(Offer(perfume_id=pid, **asdict(m), fetched_at=now))
    state = "ready" if matched else "no_match"
    record = await session.get(PriceRefresh, pid)
    if record is None:
        record = PriceRefresh(perfume_id=pid)
        session.add(record)
    record.state = state
    record.next_refresh_at = now + timedelta(days=settings.pricing_cache_days)
    await session.commit()
    return state


async def refresh_batch(items, *, factory=None):
    for pid, brand, name in items[: settings.pricing_lazy_per_request]:
        await refresh_one(pid, brand, name, factory=factory)


async def due_items(session, items):
    from app.pricing.matching import concentration

    items = [item for item in items if concentration(item[2]) is not None]
    if not items:
        return []
    states = await session.scalars(
        select(PriceRefresh).where(PriceRefresh.perfume_id.in_([item[0] for item in items]))
    )
    now = datetime.now(UTC)
    blocked = set()
    for row in states:
        next_at = row.next_refresh_at
        if next_at.tzinfo is None:
            next_at = next_at.replace(tzinfo=UTC)
        if next_at > now:
            blocked.add(row.perfume_id)
    return [item for item in items if item[0] not in blocked][: settings.pricing_lazy_per_request]
