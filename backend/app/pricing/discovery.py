"""Taste-based candidates to price; brand hints never stand in for actual prices."""

from dataclasses import replace

from app.engine.recommend import Filters, build_profile, candidate_mask, rank, similarity

# Prioritize coverage for the value houses requested by the user. Products only
# enter Budget after a matching live offer meets the user's actual price cap.
VALUE_HOUSES = frozenset(
    name.casefold()
    for name in (
        "Lattafa Perfumes",
        "Afnan",
        "Rasasi",
        "Armaf",
        "Swiss Arabian",
        "Ajmal",
        "Al Haramain Perfumes",
        "Riiffs Perfumes",
        "Khadlaj Perfumes",
        "Ard Al Zaafaran",
        "Al Wataniah",
        "Ahmed Al Maghribi",
        "Arabiyat Prestige",
        "Rayhaan",
        "Maison Alhambra",
        "Fragrance World",
        "French Avenue",
        "PARIS CORNER",
    )
)


def price_candidates(
    catalog,
    owned_ids,
    filters=None,
    *,
    ratings=None,
    disliked_ids=(),
    excluded_ids=(),
    priced_ids=(),
    limit=60,
):
    owned = catalog.rows(list(dict.fromkeys(owned_ids)))
    if len(owned) < 5:
        raise ValueError("Add at least five distinct owned fragrances")
    # Looking up an unknown price must not itself require an existing price.
    scent_filters = replace(filters or Filters(), price_min=None, price_max=None, store="any")
    mask = candidate_mask(catalog, owned, scent_filters)
    excluded = set(excluded_ids) | set(priced_ids)
    mask &= ~catalog.perfumes.id.isin(excluded).to_numpy()
    profile = build_profile(catalog, owned, ratings, disliked_ids)
    sims = similarity(catalog, profile)
    value_mask = catalog.perfumes.brand.str.casefold().isin(VALUE_HOUSES).to_numpy()
    ranked = rank(catalog, profile, mask & value_mask, sims, limit=max(limit * 3, 30))
    # Cover multiple brands before more flankers of the same house; taste ranking
    # still determines which fragrance to query first within each house.
    first, remaining, brands = [], [], set()
    for item in ranked:
        if item.brand not in brands:
            first.append(item)
            brands.add(item.brand)
        else:
            remaining.append(item)
    selected = (first + remaining)[:limit]
    if len(selected) < limit:
        selected.extend(
            rank(catalog, profile, mask & ~value_mask, sims, limit=limit - len(selected))
        )
    return [(item.id, item.brand, item.name) for item in selected]
