import math

import pandas as pd
import pytest

from pipeline.clean import USECOLS, clean


def make_row(**overrides: object) -> dict:
    row = {col: 0 for col in USECOLS}
    row.update(
        id=1,
        slug="x",
        name="X",
        brand="B",
        year=2020,
        url="u",
        gender="male",
        rating_avg=4.0,
        vote_count=100,
        longevity_avg=3.0,
        longevity_b3=10,
        winter=10,
        spring=30,
        summer=50,
        autumn=10,
        accords="citrus:100|woody:40",
        notes_top="Bergamot:100",
        notes_middle="Lavender:45",
        notes_base="Cedarwood:20",
        notes_flat=math.nan,
    )
    row.update(overrides)
    return row


def run(*rows: dict) -> pd.DataFrame:
    return clean(pd.DataFrame(list(rows)))


def test_season_shares() -> None:
    out = run(make_row()).iloc[0]
    assert out["season_share_summer"] == pytest.approx(0.5)
    assert out["warm_share"] == pytest.approx(0.8)
    assert out["cold_share"] == pytest.approx(0.2)


def test_zero_means_missing() -> None:
    row = make_row(
        rating_avg=0,
        vote_count=0,
        longevity_avg=0,
        longevity_b3=0,
        winter=0,
        spring=0,
        summer=0,
        autumn=0,
    )
    out = run(row).iloc[0]
    assert math.isnan(out["rating_avg"])
    assert math.isnan(out["longevity_avg"])
    assert math.isnan(out["warm_share"])
    assert not out["in_pool"]


def test_longevity_falls_back_to_histogram() -> None:
    out = run(make_row(longevity_avg=0, longevity_b3=0, longevity_b2=1, longevity_b4=1)).iloc[0]
    assert out["longevity_avg"] == pytest.approx(3.0)
    assert out["longevity_votes"] == 2


def test_notes_parsed_with_aliases() -> None:
    out = run(make_row()).iloc[0]
    assert out["notes_base"] == [{"name": "cedar", "weight": 20}]
    assert out["accords"][0] == {"name": "citrus", "weight": 100}


def test_flat_notes_used_when_no_pyramid() -> None:
    row = make_row(
        notes_top=math.nan, notes_middle=math.nan, notes_base=math.nan, notes_flat="Rose:80"
    )
    out = run(row).iloc[0]
    assert out["notes_middle"] == [{"name": "rose", "weight": 80}]


def test_pool_requires_votes_and_accords() -> None:
    out = run(make_row(id=1), make_row(id=2, vote_count=5), make_row(id=3, accords=math.nan))
    assert out["in_pool"].tolist() == [True, False, False]
