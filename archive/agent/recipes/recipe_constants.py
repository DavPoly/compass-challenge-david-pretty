"""Constants of the answer recipes."""

# Aggregation

# Superseded
SUPERSEDED_SEARCH_K = 8
SUPERSEDED_LIST_CAP = 200
SUPERSEDED_RRF_OFFSET = 5
SUPERSEDED_SERIES_MARGIN = 1.5
POLICY_DOC_TYPE = "policy"
SUPERSEDED_TODAY_LABEL = "today"
SUPERSEDED_NOTE_TEMPLATE = (
    "Policy version in force on {as_of}: document {doc_id}, "
    "version {version}, effective {period}. The other listed "
    "versions of this policy are superseded and must not be used "
    "for the answer."
)
SUPERSEDED_PERIOD_OPEN = "from {effective_from}"
SUPERSEDED_PERIOD_CLOSED = "from {effective_from} to {effective_to}"
