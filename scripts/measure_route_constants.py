"""Constants of the route measurement script."""

DEFAULT_QUESTIONS_PARTS = ("samples", "questions.jsonl")
DEFAULT_GOLD_PARTS = ("samples", "gold.jsonl")
ID_WIDTH = 6
TYPE_WIDTH = 14
FAMILY_WIDTH = 13
UNANSWERABLE_TYPE = "unanswerable"
GOLD_TYPE_TO_FAMILY = {
    "direct": "direct",
    "conflict": "direct",
    "aggregation": "aggregation",
    "superseded": "superseded",
    "multi_hop": "multi_hop",
}
PLAN_FIELDS = (
    "client",
    "project_manager",
    "project_codes",
    "date_from",
    "date_to",
    "as_of_date",
    "measure",
    "policy_topic",
)
MSG_NO_ANSWERABLE = "No answerable gold question to score in {path}."
MSG_ACCURACY = "family accuracy: {correct}/{total} = {ratio:.2f}"
MSG_MISSING_CONFIG = "Cannot build the LLM client: {error}"
