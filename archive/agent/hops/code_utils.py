"""Helpers on identifier codes."""

from collections.abc import Iterable

from archive.agent.hops.hop_constants import EMAIL_MARKER


def non_email_codes(codes: Iterable[str]) -> list[str]:
    """Return the codes that are not email addresses, in order."""
    return [code for code in codes if EMAIL_MARKER not in code]
