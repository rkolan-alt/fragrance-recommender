import json

import pandas as pd

from pipeline.clones import find_clones, read_similar_votes

PERFUMES = pd.DataFrame(
    [
        # id, brand, year, vote_count
        (1, "Creed", 2010, 28000),  # Aventus
        (2, "Armaf", 2015, 29000),  # Club de Nuit Intense Man (clone of 1)
        (3, "Armaf", 2018, 3000),  # an Armaf original
        (4, "Maison Alhambra", 2022, 900),  # dupe house, no votes at all
        (5, "Dior", 2015, 34000),  # Sauvage
        (6, "Lattafa Perfumes", None, 500),  # unknown year, smells like 5
        (7, "Chanel", 2010, 20000),  # designer, not a clone house
        (8, "Afnan", 2008, 100),  # older and much less popular than 2
    ],
    columns=["id", "brand", "year", "vote_count"],
).astype({"year": "Int64"})


def votes(*rows: tuple[int, int, int, int]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["a", "b", "up", "down"])


def run(*rows: tuple[int, int, int, int]) -> pd.DataFrame:
    return find_clones(PERFUMES, votes(*rows)).set_index("id")


def test_mixed_house_clone_detected_from_either_page() -> None:
    # Vote recorded on the original's page (Aventus says "smells like CdNIM").
    out = run((1, 2, 5900, 886))
    assert out.at[2, "is_clone"]
    assert out.at[2, "clone_of"] == [1]
    assert not out.at[1, "is_clone"]


def test_mixed_house_original_is_kept() -> None:
    assert not run().at[3, "is_clone"]


def test_dupe_house_is_always_a_clone() -> None:
    assert run().at[4, "is_clone"]


def test_weak_or_disputed_votes_ignored() -> None:
    assert not run((2, 1, 5, 0)).at[2, "is_clone"]  # too few up votes
    assert not run((2, 1, 100, 200)).at[2, "is_clone"]  # community disagrees


def test_later_release_cannot_be_the_original() -> None:
    # Club de Nuit (2015) is far more popular than Afnan 8, but 8 came out
    # first (2008), so 8 is not a copy of Club de Nuit.
    out = run((8, 2, 500, 10))
    assert not out.at[8, "is_clone"]


def test_unknown_year_falls_back_to_popularity() -> None:
    out = run((6, 5, 300, 20))
    assert out.at[6, "is_clone"] and out.at[6, "clone_of"] == [5]


def test_designer_brands_never_flagged() -> None:
    # Two designers that smell alike are not clones.
    assert not run((5, 7, 3000, 100)).at[5, "is_clone"]


def test_read_similar_votes() -> None:
    lines = [
        json.dumps(
            {"id": 1, "similar": {"reminds_me_of": [{"id": 2, "up_votes": 10, "down_votes": 1}]}}
        ),
        json.dumps({"id": 3, "similar": {}}),
    ]
    assert read_similar_votes(lines).values.tolist() == [[1, 2, 10, 1]]


def test_brand_match_ignores_accent_encoding() -> None:
    decomposed = "Thera Cosme\u0301ticos"  # e + combining accent
    perfumes = pd.DataFrame(
        [(1, decomposed, 2020, 100)], columns=["id", "brand", "year", "vote_count"]
    ).astype({"year": "Int64"})
    assert find_clones(perfumes, votes()).at[0, "is_clone"]
