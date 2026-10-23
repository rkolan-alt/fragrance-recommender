"""Category rows share the engine's filters, clone exclusions and ranking."""

from dataclasses import dataclass

import numpy as np

from app.engine.catalog import Catalog
from app.engine.recommend import Filters, Rec, build_profile, candidate_mask, rank, similarity


@dataclass(frozen=True)
class CategoryRow:
    key: str
    title: str
    items: list[Rec]


def recommend_rows(
    catalog: Catalog,
    owned_ids: list[int],
    filters: Filters | None = None,
    limit: int = 20,
    *,
    ratings: dict[int, int] | None = None,
    disliked_ids: tuple[int, ...] = (),
    excluded_ids: tuple[int, ...] = (),
    prices: tuple = (),
) -> list[CategoryRow]:
    owned = catalog.rows(list(dict.fromkeys(owned_ids)))
    if len(owned) < 5:
        raise ValueError("add at least five distinct owned fragrances")
    filters = filters or Filters()
    base = candidate_mask(catalog, owned, filters, prices)
    if excluded_ids:
        base[catalog.rows(list(excluded_ids))] = False

    def profile_for(seeds):
        return build_profile(catalog, seeds, ratings, disliked_ids)

    profile = profile_for(owned)
    sims = similarity(catalog, profile)
    p = catalog.perfumes
    rows = []

    def add(key, title, mask, local_profile=profile, local_sims=sims, weights=None, bonus=None):
        rows.append(
            CategoryRow(
                key,
                title,
                rank(catalog, local_profile, base & mask, local_sims, weights, limit, bonus),
            )
        )

    add("for_you", "For You", base)
    from app.pricing.service import eligible

    cap = (
        min(filters.budget_max, filters.price_max)
        if filters.price_max is not None
        else filters.budget_max
    )
    affordable = eligible(prices, price_min=filters.price_min, price_max=cap, store=filters.store)
    value = np.zeros(len(p))
    for offer in affordable:
        if offer.perfume_id in catalog.row_of:
            r = catalog.row_of[offer.perfume_id]
            value[r] = max(value[r], 0.03 / (1 + float(offer.price) / offer.size_ml))
    add("budget", f"Budget · under ${cap:g}", value > 0, bonus=value)
    for key, title, column in (
        ("spring_summer", "Spring / Summer", "warm_share"),
        ("fall_winter", "Fall / Winter", "cold_share"),
    ):
        seasonal = p[column].to_numpy() >= 0.55
        seeds = owned[seasonal[owned]]
        local = profile_for(seeds) if len(seeds) >= 2 else profile
        add(key, title, seasonal, local, similarity(catalog, local))
    add(
        "long_lasting",
        "Long-Lasting",
        ((p.longevity_avg >= 4) & (p.longevity_votes >= 30)).to_numpy(),
    )
    add(
        "hidden_gems",
        "Hidden Gems",
        ((p.quality_pct >= 0.85) & p.vote_count.between(30, 1000)).to_numpy(),
    )

    start, end = catalog.layout["accords"]
    accords = catalog.matrix[:, start:end]
    owned_strength = np.asarray(accords[owned].sum(axis=0)).ravel()
    dominant = np.asarray(accords.argmax(axis=1)).ravel()
    owned_families = set(dominant[owned])
    contrasting = ~np.isin(dominant, list(owned_families))
    if base.any():
        contrasting &= sims <= np.quantile(sims[base], 0.3)
    add(
        "something_different",
        "Something Different",
        contrasting,
        weights={"similarity": 0, "quality": 0.6, "popularity": 0.4},
    )
    for index in np.argsort(-owned_strength)[:2]:
        if owned_strength[index] > 0:
            name = catalog.accords[index]
            add(
                f"accord_{index}",
                f"Because You Love {name.title()}",
                accords[:, index].toarray().ravel() > 0,
            )
    # Pick the collection's most popular fragrance until personal ratings exist.
    seed = max(
        owned, key=lambda r: ((ratings or {}).get(int(p.at[r, "id"]), 3), p.at[r, "vote_count"])
    )
    local = profile_for(np.array([seed]))
    add(
        "because_you_own",
        f"Because You Own {p.at[seed, 'name']}",
        base,
        local,
        similarity(catalog, local),
    )
    return rows
