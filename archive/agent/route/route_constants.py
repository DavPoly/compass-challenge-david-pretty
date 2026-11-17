"""Field descriptions of the question plan shown to the LLM."""

FAMILY_DESCRIPTION = (
    "direct: one fact in one document; aggregation: a sum or count over "
    "many invoices; superseded: the policy version in force; "
    "multi_hop: needs several linked documents."
)
CLIENT_DESCRIPTION = "Client name named in the question, else null."
PROJECT_MANAGER_DESCRIPTION = "Project manager named, else null."
PROJECT_CODES_DESCRIPTION = "Project codes named in the question."
DATE_FROM_DESCRIPTION = "Inclusive ISO lower date bound, else null."
DATE_TO_DESCRIPTION = "Inclusive ISO upper date bound, else null."
AS_OF_DATE_DESCRIPTION = "ISO date the answer must hold at, else null."
MEASURE_DESCRIPTION = (
    "pre_tax or tax_included for amount questions, else null."
)
POLICY_TOPIC_DESCRIPTION = "Policy subject for superseded questions."
