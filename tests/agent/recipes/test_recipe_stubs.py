from archive.agent.recipes.aggregation_service import run_aggregation
from archive.agent.route.route_model import QuestionFamily, QuestionPlan
from archive.llm.llm_gateway import LlmGateway
from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.input_model import Question

QUESTION = Question(id="q1", question="Total ?")


class NoSearch:
    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        return []

    def list_by_filter(
        self, filters: SearchFilters, cap: int
    ) -> list[SearchHit]:
        return []


def test_recipes_defer_to_the_direct_path() -> None:
    plan = QuestionPlan(family=QuestionFamily.AGGREGATION)
    llm = LlmGateway.__new__(LlmGateway)

    assert run_aggregation(QUESTION, plan, NoSearch(), llm) is None
