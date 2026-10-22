import pandas as pd
import pytest

from app.engine import config
from app.engine.catalog import Catalog
from app.engine.recommend import (
    Filters,
    build_profile,
    line_stem,
    recommend,
    same_line,
    similarity,
)
from pipeline.features import build_features, build_scores

CITRUS = [{"name": "citrus", "weight": 100}, {"name": "aromatic", "weight": 60}]
GOURMAND = [{"name": "vanilla", "weight": 100}, {"name": "sweet", "weight": 70}]
OUD = [{"name": "oud", "weight": 100}, {"name": "woody", "weight": 60}]


def perfume(pid: int, accords: list[dict] = CITRUS, **overrides: object) -> dict:
    lead = accords[0]["name"]
    row = {
        "id": pid,
        "name": f"Perfume {pid}",
        "brand": f"Brand {pid}",
        "year": 2020,
        "gender": "male",
        "rating_avg": 4.0,
        "vote_count": 100,
        "in_pool": True,
        "longevity_avg": 3.0,
        "longevity_votes": 50,
        "season_share_winter": 0.25,
        "season_share_spring": 0.25,
        "season_share_summer": 0.25,
        "season_share_autumn": 0.25,
        "warm_share": 0.5,
        "cold_share": 0.5,
        "accords": accords,
        "notes_top": [{"name": f"{lead} note", "weight": 100}],
        "notes_middle": [{"name": "lavender", "weight": 50}],
        "notes_base": [{"name": "cedar", "weight": 50}],
        "is_clone": False,
        "clone_of": [],
    }
    row.update(overrides)
    return row


def make_catalog(*rows: dict) -> Catalog:
    # Filler perfumes give every note a document frequency ≥ 2.
    filler = [perfume(900 + i, a) for i, a in enumerate([CITRUS, GOURMAND, OUD] * 2)]
    df = pd.DataFrame([*rows, *filler])
    matrix, vocab = build_features(df)
    return Catalog.from_frames(
        df, matrix, vocab, build_scores(df), df[["id", "is_clone", "clone_of"]]
    )


def ids(recs: list) -> list[int]:
    return [r.id for r in recs]


def test_owned_perfumes_never_recommended() -> None:
    catalog = make_catalog(perfume(1), perfume(2), perfume(3))
    assert {1, 2}.isdisjoint(ids(recommend(catalog, [1, 2])))


def test_unknown_owned_id_raises() -> None:
    with pytest.raises(KeyError):
        recommend(make_catalog(perfume(1)), [12345])


def test_most_similar_ranks_first() -> None:
    catalog = make_catalog(perfume(1), perfume(2), perfume(3, GOURMAND))
    assert ids(recommend(catalog, [1]))[0] == 2


def test_quality_breaks_ties_between_equally_similar_perfumes() -> None:
    catalog = make_catalog(
        perfume(1),
        perfume(2, rating_avg=3.0, vote_count=5000),
        perfume(3, rating_avg=4.6, vote_count=5000),
    )
    ranked = ids(recommend(catalog, [1]))
    assert ranked.index(3) < ranked.index(2)


def test_clones_excluded_unless_requested() -> None:
    catalog = make_catalog(perfume(1), perfume(2, is_clone=True, clone_of=[99]))
    assert 2 not in ids(recommend(catalog, [1]))
    assert 2 in ids(recommend(catalog, [1], Filters(include_clones=True)))


def test_originals_of_an_owned_clone_never_recommended() -> None:
    catalog = make_catalog(perfume(1, is_clone=True, clone_of=[2]), perfume(2), perfume(3))
    for filters in (Filters(), Filters(include_clones=True)):
        assert 2 not in ids(recommend(catalog, [1], filters))


def test_taste_clusters_keep_distinct_tastes_apart() -> None:
    citrus = [perfume(i) for i in range(1, 4)]
    gourmand = [perfume(i, GOURMAND) for i in range(4, 7)]
    catalog = make_catalog(*citrus, *gourmand, perfume(7), perfume(8, GOURMAND))
    profile = build_profile(catalog, catalog.rows(list(range(1, 7))))
    sims = similarity(catalog, profile)
    assert len(profile.centers) == 3  # centroid + 2 clusters
    # A pure citrus perfume matches the citrus cluster, not the blurred centroid.
    assert sims[catalog.row_of[7]] == pytest.approx(1.0, abs=1e-5)
    assert sims[catalog.row_of[8]] == pytest.approx(1.0, abs=1e-5)


def test_at_most_two_per_product_line() -> None:
    flankers = ["Sauvage", "Sauvage Elixir", "Sauvage Eau de Parfum", "Sauvage Parfum"]
    rows = [perfume(10 + i, name=n, brand="Dior") for i, n in enumerate(flankers)]
    catalog = make_catalog(perfume(1), *rows)
    recommended = set(ids(recommend(catalog, [1])))
    assert len(recommended & {10, 11, 12, 13}) == config.MAX_PER_LINE


def test_line_stem() -> None:
    assert line_stem("Acqua di Giò Profumo") == ("acqua", "di", "gio")
    assert line_stem("Acqua di Giò Profondo Eau de Parfum (2024)") == (
        "acqua", "di", "gio", "profondo"
    )  # fmt: skip
    assert line_stem("Dior Homme Intense 2011") == ("dior",)
    assert line_stem("Parfum") == ("parfum",)  # never strip to nothing
    assert same_line(line_stem("Acqua di Giò Profondo"), line_stem("Acqua di Gio"))
    assert not same_line(line_stem("Acqua di Gioia"), line_stem("Acqua di Giò"))


def test_filters() -> None:
    catalog = make_catalog(
        perfume(1),
        perfume(2, gender="female"),
        perfume(3, OUD),
        perfume(4, rating_avg=3.0),
        perfume(5, season_share_summer=0.7, season_share_winter=0.0),
        perfume(6, brand="Zara"),
    )
    candidates = {2, 3, 4, 5, 6}

    def run(**kw: object) -> set[int]:
        return set(ids(recommend(catalog, [1], Filters(**kw)))) & candidates

    assert run(genders=("female",)) == {2}
    assert run(include_accords=("oud",)) == {3}
    assert 3 not in run(exclude_accords=("oud",))
    assert 4 not in run(min_rating=3.5)
    assert run(seasons=("summer",)) == {5}
    assert 6 not in run(exclude_brands=("Zara",))
    with pytest.raises(ValueError):
        run(include_accords=("not an accord",))


def test_explanation_names_closest_owned_perfume_and_shared_terms() -> None:
    catalog = make_catalog(perfume(1), perfume(2, GOURMAND), perfume(3, GOURMAND))
    rec = next(r for r in recommend(catalog, [1, 2]) if r.id == 3)
    assert rec.because_of == 2
    assert rec.shared_accords[:2] == ("vanilla", "sweet")


def test_reweighted_catalog_changes_block_importance() -> None:
    catalog = make_catalog(perfume(1, gender="male"), perfume(2, gender="female"))
    reweighted = catalog.reweighted({**config.BLOCK_WEIGHTS, "gender": 0.3, "accords": 0.2})

    def male_female(c: Catalog) -> float:
        return similarity(c, build_profile(c, c.rows([1])))[c.row_of[2]]

    # Gender is the only difference, so similarity loses exactly the gender weight.
    assert male_female(catalog) == pytest.approx(1 - config.BLOCK_WEIGHTS["gender"], abs=1e-5)
    assert male_female(reweighted) == pytest.approx(1 - 0.3, abs=1e-5)


def test_personal_ratings_weight_the_collection_profile():
    import numpy as np

    catalog = make_catalog(
        perfume(1, CITRUS), perfume(2, GOURMAND), perfume(3, CITRUS), perfume(4, GOURMAND)
    )
    owned = catalog.rows([1, 2])
    citrus_favored = similarity(catalog, build_profile(catalog, owned, {1: 5, 2: 1}))
    gourmand_favored = similarity(catalog, build_profile(catalog, owned, {1: 1, 2: 5}))
    assert citrus_favored[catalog.row_of[3]] > gourmand_favored[catalog.row_of[3]]
    assert np.all(np.isfinite(citrus_favored))


def test_disliked_centroid_reduces_similar_candidates():
    catalog = make_catalog(
        perfume(1, CITRUS), perfume(2, GOURMAND), perfume(3, CITRUS), perfume(4, GOURMAND)
    )
    owned = catalog.rows([1, 2])
    baseline = similarity(catalog, build_profile(catalog, owned))
    adjusted = similarity(catalog, build_profile(catalog, owned, disliked_ids=(3,)))
    assert baseline[catalog.row_of[3]] - adjusted[catalog.row_of[3]] > (
        baseline[catalog.row_of[4]] - adjusted[catalog.row_of[4]]
    )
