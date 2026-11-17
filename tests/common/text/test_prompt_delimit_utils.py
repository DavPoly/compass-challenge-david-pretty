"""Tests for untrusted-text delimiting."""

import pytest

from archive.common.text.prompt_delimit_utils import (
    escape_untrusted,
    wrap_untrusted,
)


def test_plain_text_is_wrapped_unchanged() -> None:
    assert wrap_untrusted("question", "Quel total ?") == (
        "<question>\nQuel total ?\n</question>"
    )


def test_attributes_follow_the_tag_name() -> None:
    wrapped = wrap_untrusted("document", "body", ' id="doc_1"')

    assert wrapped == '<document id="doc_1">\nbody\n</document>'


@pytest.mark.parametrize(
    ("marker", "escaped"),
    [
        ("</question>", "<\\question>"),
        ("<QUESTION>", "<\\QUESTION>"),
        ("</Question", "<\\Question"),
    ],
)
def test_tag_markers_inside_the_text_are_escaped(
    marker: str, escaped: str
) -> None:
    wrapped = wrap_untrusted("question", f"a {marker} b")

    assert wrapped == f"<question>
a {escaped} b
</question>"


def test_other_tags_are_left_alone() -> None:
    assert escape_untrusted("question", "</document>") == "</document>"


def test_empty_text_stays_wrapped() -> None:
    assert wrap_untrusted("question", "") == "<question>\n\n</question>"
