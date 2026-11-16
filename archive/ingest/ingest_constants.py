"""Constants of the ingest package: chunking, metadata and index build."""

from archive.common.constants import STOPWORDS_EN, STOPWORDS_FR

CHUNK_SINGLE_MAX_TOKENS = 800
CHUNK_TARGET_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 50
CHUNK_PARAGRAPH_SNAP_TOKENS = 60
CHUNK_ID_SEPARATOR = "#"
PARAGRAPH_BREAK = "\n\n"
# Tokens are approximated by whitespace-separated words.
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

MANIFEST_FILE_NAME = "manifest.json"
MANIFEST_INDENT = 1
BUILD_FLUSH_CHUNKS = 512
BUILD_MAP_CHUNKSIZE = 8
FILE_HASH_BLOCK_BYTES = 1 << 20
