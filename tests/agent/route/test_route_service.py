from archive.agent.route.route_model import QuestionFamily, QuestionPlan
from archive.agent.route.route_service import plan_question
from archive.llm.llm_gateway import LlmGateway
from archive.validation.input_model import Question


def test_plan_defaults_are_empty() -> None:
    plan = QuestionPlan(family=QuestionFamily.DIRECT)

    assert plan.client is None
    assert plan.project_codes == []
    assert plan.measure is None


def test_stub_plan_is_direct() -> None:
    question = Question(id="q1", question="Quel est le total ?")

    plan = plan_question(question, LlmGateway.__new__(LlmGateway))

    assert plan.family is QuestionFamily.DIRECT
