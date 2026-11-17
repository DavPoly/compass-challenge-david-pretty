"""Tests for the full-date and month-year finders."""

import pytest

from archive.common.text.date_parsing_utils import (
    find_first_date,
    find_month_year,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("le 1er janvier 2027", "2027-01-01"),
        ("on 1st March 2024", "2024-03-01"),
        ("12 mars 2024", "2024-03-12"),
        ("March 12, 2024", "2024-03-12"),
        ("2024-03-12", "2024-03-12"),
        ("12/03/2024", "2024-03-12"),
        ("25/09/19", "2019-09-25"),
        ("le 3 Septembr 2024", "2024-09-03"),
        ("31 février 2024", None),
        ("rien", None),
        ("", None),
    ],
)
def test_find_first_date(text: str, expected: str | None) -> None:
    assert find_first_date(text) == expected


def test_earliest_date_by_position_wins() -> None:
    assert find_first_date("a 2024-05-01 puis 1er mars 2020") == "2024-05-01"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Période : août 2023", "2023-08-01"),
        ("Period: March 2022", "2022-03-01"),
        ("décembre 2023", "2023-12-01"),
        ("Period: Marhc 2022", "2022-03-01"),
        ("Period: banana 2022", None),
        ("août", None),
        ("", None),
    ],
)
def test_find_month_year(text: str, expected: str | None) -> None:
    assert find_month_year(text) == expected
