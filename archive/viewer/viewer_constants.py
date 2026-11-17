"""Constants for the static run viewer."""

from pathlib import Path

VIEWER_DPI = 110
VIEWER_GRACE_S = 90.0
TEMPLATE_PATH = Path(__file__).parent / "template" / "viewer_template.html"
DATA_PLACEHOLDER = "__VIEWER_DATA__"
INDEX_FILENAME = "index.html"
PAGES_DIRNAME = "pages"
VIEWER_ENCODING = "utf-8"
RETRIEVED_LIMIT = 10
ACCURACY_DECIMALS = 3
TRACE_GLOB = "*.json"
ISSUE_SEPARATOR = ":"

CONFIDENCE_UNKNOWN = "unknown"
CONFIDENCE_LABELS = ("high", "medium", "low", CONFIDENCE_UNKNOWN)

SCORE_ROWS_KEY = "rows"
SCORE_ID_KEY = "id"
SCORE_OK_KEY = "ok"
SCORE_EXPECTED_KEY = "expected_answer"

# Characters unsafe inside <script>, mapped to valid JSON escapes.
SCRIPT_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}

IGNORED_ISSUE_CODES = frozenset({"normalized"})
REASON_ANSWER_TOO_LONG = "réponse trop longue, tronquée"
REASON_BY_ISSUE_CODE = {
    "answer_too_long": REASON_ANSWER_TOO_LONG,
    "citations_dropped": "citations absentes du corpus écartées",
    "no_valid_citation": "aucune citation valide",
    "conflict_citations": "citations contradictoires",
    "not_found_cleared": "réponse effacée : aucune information trouvée",
    "quote_unverified": "une citation n'a pas été retrouvée dans les sources",
    "value_ungrounded": "valeur de la réponse non appuyée par les preuves",
    "no_evidence": "aucune preuve",
}
REASON_EVIDENCE_INSUFFICIENT = "brouillon jugé insuffisant par le modèle"

LOG_TRACE_SKIPPED = "viewer: skipping unreadable trace %s"
LOG_RENDER_FAILED = "viewer: cannot render evidence %s of question %s"
LOG_BUDGET_EXHAUSTED = "viewer: time budget exhausted, text-only evidence"
LOG_SCORES_UNUSABLE = "viewer: scores file %s unusable, page is unscored"
LOG_VIEWER_WRITTEN = "viewer: wrote %s"

MSG_TEMPLATE_MISSING = (
    "Viewer template not found at {path}; reinstall or restore it."
)
MSG_PLACEHOLDER_MISSING = (
    "Viewer template {path} has no {placeholder} placeholder."
)
