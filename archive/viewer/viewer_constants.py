"""Constants for the static run viewer."""

from pathlib import Path

VIEWER_DPI = 110
POINTS_PER_INCH = 72
CROP_MARGIN_Y_PT = 36.0
FALLBACK_PAGE_NUMBER = 1
FULL_SUFFIX = "_page.png"
CROP_SUFFIX = "_crop.png"
OVERLAY_ALPHA = 70
OUTLINE_WIDTH_PX = 2
VALUE_OUTLINE_WIDTH_PX = 3
VERIFIED_RGB = (30, 160, 70)
UNVERIFIED_RGB = (210, 50, 50)
VALUE_VERIFIED_RGB = (0, 90, 30)
VALUE_UNVERIFIED_RGB = (130, 0, 0)
LINE_TOP_TOLERANCE_PT = 3.0
VIEWER_GRACE_S = 90.0
TEMPLATE_PATH = Path(__file__).parent / "template" / "viewer_template.html"
DATA_PLACEHOLDER = "__VIEWER_DATA__"
# Template token -> sibling file inlined in its place (CSS and JS).
INLINE_ASSETS = (
    ("/*__VIEWER_STYLES__*/", "viewer_styles.css"),
    ("/*__VIEWER_DOM__*/", "viewer_dom.js"),
    ("/*__VIEWER_APP__*/", "viewer_app.js"),
    ("/*__VIEWER_LIVE__*/", "viewer_live.js"),
)
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
LOG_DOC_OUTSIDE_CORPUS = (
    "viewer: doc id %r is outside the corpus, not rendered"
)
LOG_RENDER_FAILED = "viewer: cannot render evidence %s of question %s"
LOG_BUDGET_EXHAUSTED = "viewer: time budget exhausted, text-only evidence"
LOG_SCORES_UNUSABLE = "viewer: scores file %s unusable, page is unscored"
LOG_VIEWER_WRITTEN = "viewer: wrote %s"

MSG_TEMPLATE_MISSING = (
    "Viewer template not found at {path}; reinstall or restore it."
)
MSG_ASSET_MISSING = (
    "Viewer asset {path} (token {token}) not found; restore it."
)
MSG_PLACEHOLDER_MISSING = (
    "Viewer template {path} has no {placeholder} placeholder."
)
