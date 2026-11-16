"""Tests for the shared month tables and date patterns."""

from archive.common.text.date_parsing_constants import (
    MONTH_ABBREVIATIONS,
    MONTH_FULL_NAMES,
    MONTHS,
)

EXPECTED_MONTH_FULL_NAMES = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

EXPECTED_MONTH_ABBREVIATIONS = {
    "janv": 1,
    "jan": 1,
    "fevr": 2,
    "fev": 2,
    "feb": 2,
    "mar": 3,
    "avr": 4,
    "apr": 4,
    "jun": 6,
    "juil": 7,
    "jul": 7,
    "aug": 8,
    "sept": 9,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

EXPECTED_MONTHS = {
    "janvier": 1,
    "janv": 1,
    "january": 1,
    "jan": 1,
    "fevrier": 2,
    "fevr": 2,
    "fev": 2,
    "february": 2,
    "feb": 2,
    "mars": 3,
    "march": 3,
    "mar": 3,
    "avril": 4,
    "avr": 4,
    "april": 4,
    "apr": 4,
    "mai": 5,
    "may": 5,
    "juin": 6,
    "june": 6,
    "jun": 6,
    "juillet": 7,
    "juil": 7,
    "july": 7,
    "jul": 7,
    "aout": 8,
    "august": 8,
    "aug": 8,
    "septembre": 9,
    "sept": 9,
    "september": 9,
    "sep": 9,
    "octobre": 10,
    "oct": 10,
    "october": 10,
    "novembre": 11,
    "nov": 11,
    "november": 11,
    "decembre": 12,
    "dec": 12,
    "december": 12,
}


def test_month_full_names_are_the_full_french_and_english_names() -> None:
    assert MONTH_FULL_NAMES == EXPECTED_MONTH_FULL_NAMES


def test_month_abbreviations_are_the_short_forms_only() -> None:
    assert MONTH_ABBREVIATIONS == EXPECTED_MONTH_ABBREVIATIONS


def test_months_is_the_merge_of_full_names_and_abbreviations() -> None:
    assert MONTHS == {**MONTH_FULL_NAMES, **MONTH_ABBREVIATIONS}
    assert not MONTH_FULL_NAMES.keys() & MONTH_ABBREVIATIONS.keys()


def test_months_value_is_stable() -> None:
    assert MONTHS == EXPECTED_MONTHS
