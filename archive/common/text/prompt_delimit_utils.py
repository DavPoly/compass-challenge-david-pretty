"""Delimit untrusted text inside LLM prompts."""

import re

from archive.common.constants import (
    UNTRUSTED_BLOCK,
    UNTRUSTED_TAG_ESCAPE,
    UNTRUSTED_TAG_PATTERN,
)


def escape_untrusted(tag: str, text: str) -> str:
    """Neutralise any opening or closing `tag` marker found in `text`.

    `<tag` and `</tag` (any case) become `<\\tag`, so the text cannot
    close or fake a delimited block.

    Args:
        tag: Tag name to protect, e.g. ``question``.
        text: Untrusted text.

    Returns:
        The text with the tag markers escaped.
    """
    pattern = re.compile(
        UNTRUSTED_TAG_PATTERN.format(tag=re.escape(tag)), re.IGNORECASE
    )
    return pattern.sub(UNTRUSTED_TAG_ESCAPE.format(tag=tag), text)


def wrap_untrusted(tag: str, text: str, attributes: str = "") -> str:
    """Wrap `text` in `<tag>` delimiters after escaping that tag in it.

    Args:
        tag: Tag name, e.g. ``document``.
        text: Untrusted text.
        attributes: Raw attribute text placed after the tag name,
            including its leading space, e.g. ``' id="doc_1"'``.

    Returns:
        The delimited block, without a trailing newline.
    """
    return UNTRUSTED_BLOCK.format(
        tag=tag,
        attributes=attributes,
        text=escape_untrusted(tag, text),
    )
