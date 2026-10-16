import numpy as np
import pandas as pd

from pipeline.evaluate import build_truth, engine, evaluate, popular
from tests.test_engine import GOURMAND, make_catalog, perfume


def votes(*rows: tuple[int, int, int, int]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["a", "b", "up", "down"])


def test_truth_is_symmetric_and_needs_agreement() -> None:
    catalog = make_catalog(perfume(1), perfume(2), perfume(3), perfume(4))
    truth = build_truth(votes((1, 2, 50, 5), (1, 3, 3, 0), (1, 4, 50, 100)), catalog)
    r = catalog.row_of
    assert truth[r[1]] == {r[2]} and truth[r[2]] == {r[1]}


def test_engine_finds_similar_target_that_popularity_misses() -> None:
    catalog = make_catalog(
        perfume(1, GOURMAND),
        perfume(2, GOURMAND, vote_count=40),  # the "smells like" target
        perfume(3, vote_count=50_000),  # popular, but citrus
    )
    truth = build_truth(votes((1, 2, 50, 0)), catalog)
    queries = {"single": [np.array([catalog.row_of[1]])]}
    assert evaluate(catalog, truth, queries, engine(), k=3)["single hit@3"] == 1.0
    assert evaluate(catalog, truth, queries, popular, k=3)["single hit@3"] == 0.0


def test_baselines_never_fill_with_excluded_candidates() -> None:
    from pipeline.evaluate import random_popular

    catalog = make_catalog(perfume(1), perfume(2))
    mask = np.zeros(len(catalog.perfumes), dtype=bool)
    mask[1] = True
    for method in (popular, random_popular(0)):
        assert method(catalog, np.array([0]), mask, 20) == [1]
        assert method(catalog, np.array([0]), mask & False, 20) == []
