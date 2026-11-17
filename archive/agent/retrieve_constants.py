"""Constants of the retrieval step: top-k and doc-type keyword table."""

from archive.common.chunk_model import DocType

SEARCH_TOP_K = 8
# Share of the k slots reserved for hits filtered on the hinted types.
RETRIEVE_TYPED_SHARE = 0.5

# Regex patterns matched on `normalize_for_match(question)` (lowercase,
# no accents). Deliberately left out, because they cause false hints:
# - courriel / email / e-mail: questions ask for the email address of a
#   person, which lives in contracts and the directory, not in emails.
# - poste, salaire / salary: "poste" means job as often as extension,
#   and salary questions target contracts, not the directory.
# - bare "rapport" / "report": too generic; only the monthly form hints.
DOC_TYPE_KEYWORDS: dict[DocType, tuple[str, ...]] = {
    DocType.INVOICE: (r"\bfactur\w*", r"\binvoic\w*", r"\bbilled\b"),
    DocType.POLICY: (r"\bpolitiques?\b", r"\bpolic(?:y|ies)\b"),
    DocType.CONTRACT: (r"\bcontrats?\b", r"\bcontracts?\b"),
    DocType.MINUTES: (
        r"\breunions?\b",
        r"\bmeetings?\b",
        r"\bproces-verbal\b",
        r"\bproces-verbaux\b",
        r"\bminutes of\b",
    ),
    DocType.MONTHLY_REPORT: (
        r"\brapports? mensuels?\b",
        r"\bmonthly reports?\b",
    ),
    DocType.DIRECTORY: (
        r"\bbottin\b",
        r"\bannuaire\b",
        r"\bstaff directory\b",
        r"\bdirectory\b",
    ),
}
