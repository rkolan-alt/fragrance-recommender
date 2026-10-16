import pytest

from app.engine.categories import recommend_rows
from app.engine.recommend import Filters
from tests.test_engine import make_catalog, perfume


def test_rows_preserve_owned_and_clone_exclusions_and_filters():
    catalog = make_catalog(
        *(perfume(i) for i in range(1, 6)),
        perfume(6, is_clone=True),
        perfume(7, gender="female"),
        perfume(8, warm_share=0.8, cold_share=0.2),
    )
    rows = recommend_rows(catalog, [1, 2, 3, 4, 5], Filters(genders=("male",)))
    assert rows[0].items
    for row in rows:
        ids = [r.id for r in row.items]
        assert len(ids) == len(set(ids))
        assert not set(ids) & {1, 2, 3, 4, 5, 6, 7}
    seasonal = next(r for r in rows if r.key == "spring_summer")
    assert [r.id for r in seasonal.items] == [8]


def test_minimum_counts_distinct_owned_perfumes():
    with pytest.raises(ValueError, match="five distinct"):
        recommend_rows(make_catalog(perfume(1)), [1] * 5)


def test_restrictive_filters_return_empty_rows():
    catalog = make_catalog(*(perfume(i) for i in range(1, 6)))
    assert all(
        not r.items for r in recommend_rows(catalog, [1, 2, 3, 4, 5], Filters(min_votes=10**9))
    )
