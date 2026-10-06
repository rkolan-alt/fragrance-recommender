import math

from pipeline.parsing import NOTE_ALIASES, parse_weighted


def test_basic() -> None:
    assert parse_weighted("Bergamot:49|Lemon:5") == [("bergamot", 49), ("lemon", 5)]


def test_empty_values() -> None:
    assert parse_weighted(None) == []
    assert parse_weighted(math.nan) == []
    assert parse_weighted("") == []


def test_name_containing_pipe_is_rejoined() -> None:
    value = "Eustoma | Lisianthus:83|Grasse Rose:83"
    assert parse_weighted(value) == [("eustoma | lisianthus", 83), ("grasse rose", 83)]


def test_name_containing_colon_splits_on_last_colon() -> None:
    assert parse_weighted("Note: Special:40|Musk:10") == [("note: special", 40), ("musk", 10)]


def test_whitespace_and_case_normalized() -> None:
    assert parse_weighted("  Fresh   Spicy :100") == [("fresh spicy", 100)]


def test_aliases_merge_and_keep_max_weight() -> None:
    value = "Virginia Cedar:17|Cedar:30|White Musk:5"
    assert parse_weighted(value, NOTE_ALIASES) == [("cedar", 30), ("musk", 5)]


def test_trailing_unweighted_piece_is_dropped() -> None:
    assert parse_weighted("Musk:10|Broken") == [("musk", 10)]
