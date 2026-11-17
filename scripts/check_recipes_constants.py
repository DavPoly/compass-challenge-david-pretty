"""Constants of the recipe check script."""

from archive.agent.route.route_model import (
    AmountMeasure,
    QuestionFamily,
    QuestionPlan,
)

DEFAULT_GOLD_PARTS = ("samples", "gold.jsonl")
AGGREGATION_IDS = ("s07", "s10", "s20")
SUPERSEDED_IDS = ("s01", "s12", "s17")
FALLBACK_IDS = ("s18",)
FALLBACK_LABEL = "fallback"
PLANS: dict[str, QuestionPlan] = {
    "s07": QuestionPlan(
        family=QuestionFamily.AGGREGATION,
        client="Grayheron Logistics Ltd.",
        date_from="2023-01-01",
        date_to="2023-12-31",
        measure=AmountMeasure.PRE_TAX,
    ),
    "s10": QuestionPlan(
        family=QuestionFamily.AGGREGATION,
        project_codes=["BRV-2021-12"],
        measure=AmountMeasure.TAX_INCLUDED,
    ),
    "s20": QuestionPlan(
        family=QuestionFamily.AGGREGATION,
        project_manager="Priya Lavoie",
        date_from="2025-01-01",
        date_to="2025-12-31",
        measure=AmountMeasure.PRE_TAX,
    ),
    "s01": QuestionPlan(
        family=QuestionFamily.SUPERSEDED,
        as_of_date="2023-11-18",
        policy_topic="politique d'allocation de repas",
    ),
    "s12": QuestionPlan(
        family=QuestionFamily.SUPERSEDED,
        policy_topic="Expense Claims Policy",
    ),
    "s17": QuestionPlan(
        family=QuestionFamily.SUPERSEDED,
        policy_topic="politique de remboursement des frais de déplacement",
    ),
    "s18": QuestionPlan(
        family=QuestionFamily.AGGREGATION,
        date_from="2024-01-01",
        date_to="2024-12-31",
    ),
}
MSG_AGGREGATION = (
    "{id} aggregation {verdict}: answer={answer} gold={gold} "
    "citations={count} missing={missing} extra={extra}"
)
MSG_SUPERSEDED = "{id} superseded: first_hit={first} gold={gold}"
MSG_FALLBACK = "{id} fallback: {verdict}"
MSG_SUMMARY = "recipes check: {verdict}"
MSG_MISSING_GOLD = "No gold row for {ids} in {path}."
MSG_DENSE_UNAVAILABLE = "Dense model unavailable; BM25 only."
VERDICT_OK = "OK"
VERDICT_DIFF = "DIFF"
VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
LLM_OFFLINE_MESSAGE = "LLM disabled for the recipe check."
