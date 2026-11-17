"""Plan a question: pick its family and extract filters."""

from archive.agent.route.route_model import QuestionFamily, QuestionPlan
from archive.llm.llm_gateway import LlmGateway
from archive.retrieval.search_service import find_identifiers
from archive.validation.input_model import Question


def plan_question(question: Question, llm: LlmGateway) -> QuestionPlan:
    """Return the plan of a question.

    Currently every question is `direct`; identifiers found in the text
    become the plan's project codes. `llm` is reserved for the
    LLM-backed router.
    """
    return QuestionPlan(
        family=QuestionFamily.DIRECT,
        project_codes=find_identifiers(question.question),
    )
