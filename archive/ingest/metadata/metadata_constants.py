"""Constants of the metadata service: identifiers and language."""

import re

from archive.common.chunk_model import DocType
from archive.common.constants import STOPWORDS_EN, STOPWORDS_FR

LANG_FR = "fr"
LANG_EN = "en"
LANG_WORD_PATTERN = r"[a-z]+"
LANG_HINTS_FR = STOPWORDS_FR - STOPWORDS_EN
LANG_HINTS_EN = STOPWORDS_EN - STOPWORDS_FR

# Identifiers, tolerant of OCR-like typos: any dash, a space or nothing
# as separator, "O" for "0". Group "prefix" selects the canonical form.
IDENTIFIER_DASH_CHARS = "-\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
ID_SEPARATOR_PATTERN = rf"[{re.escape(IDENTIFIER_DASH_CHARS)}\s]?"
IDENTIFIER_PATTERN = (
    r"(?<![A-Za-z0-9])(?P<prefix>(?i:BRV|F|C))"
    rf"(?P<sep>{ID_SEPARATOR_PATTERN})"
    r"(?P<year>[12][09O][0-9O]{2})"
    rf"{ID_SEPARATOR_PATTERN}"
    r"(?P<serial>[0-9O]{2,4})(?![0-9])"
)
IDENTIFIER_SERIAL_DIGITS = {"F": 4, "C": 2, "BRV": 2}
EMAIL_PATTERN = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"

# Document type detection: the first title phrase found in the header
# decides. Phrases are accent-free, lowercase word sequences, matched
# with typo tolerance (see `PHRASE_FUZZY_*`).
DOC_TYPE_HEADER_LINES = 12
HEADER_WORD_PATTERN = r"[a-z0-9]+"
PHRASE_FUZZY_CUTOFF = 0.8
PHRASE_FUZZY_MIN_LENGTH = 5
EMAIL_HEADER_PATTERN = r"(?:de|from)\s*:\s*\S"
DOC_TYPE_PHRASES: dict[DocType, tuple[str, ...]] = {
    DocType.INVOICE: ("facture n", "invoice no"),
    DocType.CONTRACT: (
        "contrat de",
        "contrat n",
        "contract",
        "agreement no",
    ),
    DocType.MONTHLY_REPORT: (
        "rapport mensuel",
        "monthly progress report",
    ),
    DocType.MINUTES: (
        "reunion de chantier",
        "proces verbal",
        "site meeting",
        "minutes",
    ),
    DocType.NEWSLETTER: ("brumeval monthly", "bulletin"),
    DocType.MEMO: ("note de service", "memo"),
    DocType.POLICY: ("politique", "policy"),
    DocType.DIRECTORY: (
        "bottin du personnel",
        "staff directory",
        "liste des fournisseurs",
    ),
    DocType.TECHNICAL_NOTE: ("note technique", "technical note"),
    DocType.PROJECT_SHEET: ("fiche de projet", "project charter"),
}

# Header dates: a labelled line ("Date : ...", "En vigueur le ...",
# "Period: March 2022") is searched before the rest of the text.
DATE_HEADER_LINES = 15
DATE_LABEL_PATTERN = (
    r"(?:^|[—–-]\s*)"
    r"(?:(?:date du rapport|report date|date|mise a jour|periode|period)"
    r"\s*:|en vigueur le\b|ef+\w?ective\b)\s*(?P<rest>.*)"
)

# Version line: "Version 3 - En vigueur le ...", just under the title.
VERSION_HEADER_LINES = 6
VERSION_LINE_PATTERN = r"v\w{0,2}rsion\s+(?P<number>\d+)\b(?P<rest>.*)"
SERIES_NOISE_PATTERN = r"[^a-z0-9]+"
SERIES_SEPARATOR = " "
