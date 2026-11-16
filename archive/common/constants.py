"""Constantes partagées par plusieurs modules."""

from pathlib import Path
from typing import Final

ENV_LLM_BASE_URL = "LLM_BASE_URL"
ENV_LLM_API_KEY = "LLM_API_KEY"
ENV_LLM_MODEL = "LLM_MODEL"

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR_NAME = "corpus"
INDEX_DIR_NAME = "index"

API_KEY_MASK = "***"

STOPWORDS_FR = frozenset(
    """
    a au aux avec ce ces cet cette dans de des du elle elles en est et il
    ils je la le les leur leurs lui ma mais me mes moi mon ne nos notre
    nous ou par pas pour qu que qui sa se ses son sur ta te tes toi ton tu
    un une vos votre vous y ete etre sont sera ont avait avoir fait comme
    plus si sans sous tout tous toute toutes aussi donc car ni quel quelle
    quels quelles combien quoi dont ainsi cela celui celle
    """.split()
)

STOPWORDS_EN = frozenset(
    """
    a an and are as at be been but by can did do does for from had has have
    he her his how i if in into is it its me my no not of on or our she so
    than that the their them then there these they this those to too us
    was we were what when where which who whom why will with would you
    your
    """.split()
)

STOPWORDS = STOPWORDS_FR | STOPWORDS_EN

# --- Ingestion: text normalization, chunking, metadata -----------------

UNICODE_COMPAT_FORM: Final = "NFKC"
UNICODE_DECOMPOSED_FORM: Final = "NFKD"
HORIZONTAL_SPACE_PATTERN = r"[ \t\f\v]+"
BLANK_LINES_PATTERN = r"\n{3,}"
PAGE_SEPARATOR = "\n\n"

# Tokens are approximated by whitespace-separated words.
CHUNK_SINGLE_MAX_TOKENS = 800
CHUNK_TARGET_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 50
CHUNK_PARAGRAPH_SNAP_TOKENS = 60
CHUNK_ID_SEPARATOR = "#"
PARAGRAPH_BREAK = "\n\n"
WORD_PATTERN = r"\S+"

DOC_TYPE_UNKNOWN = "unknown"
LANG_FR = "fr"
LANG_EN = "en"
LANG_WORD_PATTERN = r"[a-z]+"
LANG_HINTS_FR = STOPWORDS_FR - STOPWORDS_EN
LANG_HINTS_EN = STOPWORDS_EN - STOPWORDS_FR

# Identifiers, tolerant of OCR-like typos: any dash, a space or nothing
# as separator, "O" for "0". Group "prefix" selects the canonical form.
ID_SEPARATOR_PATTERN = r"[-\u2010-\u2015\u2212\s]?"
IDENTIFIER_PATTERN = (
    r"(?<![A-Za-z0-9])(?P<prefix>(?i:BRV|F|C))"
    rf"(?P<sep>{ID_SEPARATOR_PATTERN})"
    r"(?P<year>[12][09O][0-9O]{2})"
    rf"{ID_SEPARATOR_PATTERN}"
    r"(?P<serial>[0-9O]{2,4})(?![0-9])"
)
IDENTIFIER_DASH_CHARS = "-\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
IDENTIFIER_SERIAL_DIGITS = {"F": 4, "C": 2, "BRV": 2}
EMAIL_PATTERN = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"

# Dates.
DATE_ISO_PATTERN = r"(?<![\d-])(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?!\d)"
DATE_NUMERIC_PATTERN = (
    r"(?<![\d/.])(?P<d>\d{1,2})[/.](?P<m>\d{1,2})[/.]"
    r"(?P<y>\d{4})(?![\d/.])"
)
DATE_SHORT_YEAR_PATTERN = (
    r"(?<![\d/.])(?P<d>\d{2})/(?P<m>\d{2})/(?P<y>\d{2})(?![\d/.])"
)
DATE_DAY_MONTH_WORD_PATTERN = (
    r"(?<!\d)(?P<d>\d{1,2})(?:er|st|nd|rd|th)?\s+"
    r"(?P<m>[^\W\d_]{3,12})\.?,?\s+(?P<y>\d{4})(?!\d)"
)
DATE_MONTH_WORD_DAY_PATTERN = (
    r"(?<![^\W\d_])(?P<m>[^\W\d_]{3,12})\.?\s+(?P<d>\d{1,2})"
    r"(?:st|nd|rd|th)?,?\s+(?P<y>\d{4})(?!\d)"
)
SHORT_YEAR_CENTURY = 2000
SHORT_YEAR_DIGITS = 2
MONTH_FUZZY_MIN_LENGTH = 4
MONTH_FUZZY_CUTOFF = 0.8
MONTH_NUMBERS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}  # fmt: skip
