import numpy as np
import pandas as pd
import pytest

from app.engine import config
from pipeline.features import arc, build_features, build_scores, note_parents


def perfume(pid: int, **overrides: object) -> dict:
    row = {
        "id": pid,
        "gender": "male",
        "rating_avg": 4.0,
        "vote_count": 100,
        "in_pool": True,
        "longevity_avg": 3.0,
        "season_share_winter": 0.25,
        "season_share_spring": 0.25,
        "season_share_summer": 0.25,
        "season_share_autumn": 0.25,
        "accords": [{"name": "citrus", "weight": 100}],
        "notes_top": [{"name": "bergamot", "weight": 100}],
        "notes_middle": [{"name": "lavender", "weight": 50}],
        "notes_base": [{"name": "cedar", "weight": 50}],
    }
    row.update(overrides)
    return row


def similarity(a: dict, b: dict, filler: int = 3) -> float:
    # Filler perfumes give every note a document frequency ≥ 2.
    rows = [a, b] + [perfume(100 + i) for i in range(filler)]
    matrix, _ = build_features(pd.DataFrame(rows))
    return float((matrix[0] @ matrix[1].T).toarray()[0, 0])


def test_block_weights_sum_to_one() -> None:
    assert sum(config.BLOCK_WEIGHTS.values()) == pytest.approx(1.0)


def test_identical_perfumes_have_similarity_one() -> None:
    assert similarity(perfume(1), perfume(2)) == pytest.approx(1.0, abs=1e-5)


def test_similarity_is_weighted_sum_of_blocks() -> None:
    # Opposite gender is the only difference: lose exactly the gender weight.
    sim = similarity(perfume(1, gender="male"), perfume(2, gender="female"))
    assert sim == pytest.approx(1 - config.BLOCK_WEIGHTS["gender"], abs=1e-5)


def test_unisex_is_between_male_and_female() -> None:
    male_unisex = similarity(perfume(1, gender="male"), perfume(2, gender="unisex"))
    male_female = similarity(perfume(1, gender="male"), perfume(2, gender="female"))
    assert male_female < male_unisex < 1


def test_arc_dot_product_is_cosine_of_gap() -> None:
    weak, medium, close, eternal = arc(np.array([0.0, 0.5, 0.6, 1.0]))
    assert weak @ weak == pytest.approx(1.0)
    assert weak @ eternal == pytest.approx(0.0, abs=1e-9)
    assert medium @ close > medium @ eternal


def test_note_parents() -> None:
    names = {"bergamot", "calabrian bergamot", "water", "orange flower water", "pepper"}
    parents = note_parents(names)
    assert parents["calabrian bergamot"] == "bergamot"
    assert "orange flower water" not in parents  # generic parent skipped
    assert "pepper" not in parents


def test_quality_shrinks_low_vote_ratings_toward_mean() -> None:
    df = pd.DataFrame(
        [
            perfume(1, rating_avg=4.8, vote_count=10),
            perfume(2, rating_avg=4.4, vote_count=20_000),
            perfume(3, rating_avg=3.0, vote_count=20_000),
        ]
    )
    quality = build_scores(df).set_index("id")["quality"]
    assert quality[2] > quality[1]
