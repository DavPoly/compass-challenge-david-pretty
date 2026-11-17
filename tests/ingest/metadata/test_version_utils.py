"""Tests for policy version parsing."""

import pytest

from archive.ingest.metadata.version_utils import (
    VersionInfo,
    parse_version,
    series_key,
)


@pytest.mark.parametrize(
    ("line", "version", "effective_from"),
    [
        ("Version 3 — En vigueur le 1er janvier 2027", "3", "2027-01-01"),
        ("Version 2 — Effective 2022-08-24", "2", "2022-08-24"),
        ("Version 2 — Efffective November 1, 2022", "2", "2022-11-01"),
        ("Version 1 — En vigueur le 25/09/19", "1", "2019-09-25"),
        ("Version 1 — En vigueur le 15 février 2025", "1", "2025-02-15"),
        ("Version 5 — En vigueur le 5 decembre 2022", "5", "2022-12-05"),
    ],
)
def test_version_line_formats(
    line: str, version: str, effective_from: str
) -> None:
    info = parse_version(f"Politique X\n{line}")

    assert info is not None
    assert info.version == version
    assert info.effective_from == effective_from


def test_title_spelling_variants_share_a_series() -> None:
    accented = parse_version(
        "Politique de télétravail\nVersion 3 — 2024-05-26"
    )
    plain = parse_version("Politique de teletravail\nVersion 2 — 2022-12-05")

    assert accented is not None
    assert plain is not None
    assert accented.series == plain.series == "politique de teletravail"


def test_boilerplate_above_the_title_is_not_the_series() -> None:
    text = (
        "Brumeval Ingénierie inc. — Document interne\n"
        "Employee Referral Policy\n"
        "Version 1 — Effective 2020-03-01"
    )

    assert parse_version(text) == VersionInfo(
        "1", "2020-03-01", "employee referral policy"
    )


def test_version_without_a_date_keeps_effective_from_empty() -> None:
    info = parse_version("Politique X\nVersion 2 — brouillon")

    assert info == VersionInfo("2", None, "politique x")


def test_text_without_version_line_gives_none() -> None:
    assert parse_version("Politique X\n1. Objet\nTexte") is None


def test_version_line_without_a_title_above_gives_none() -> None:
    assert parse_version("Version 2 — En vigueur le 2022-01-01") is None


def test_empty_text_gives_none() -> None:
    assert parse_version("") is None


def test_series_key_drops_punctuation_and_extra_spaces() -> None:
    assert series_key("  Politique d'hébergement   en déplacement ") == (
        "politique d hebergement en deplacement"
    )
