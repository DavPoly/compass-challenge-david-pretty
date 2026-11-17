"""Recipe result and the search port recipes depend on."""

from dataclasses import dataclass
from typing import Protocol

from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.answer_model import DraftAnswer


@dataclass(frozen=True)
class RecipeResult:
    """Outcome of a recipe.

    Attributes:
        hits: Chunks the recipe used or listed, in prompt order.
        draft: A finished answer; when set, no draft call is made.
        note: Extra context rendered into the draft prompt.
    """

    hits: list[SearchHit]
    draft: DraftAnswer | None = None
    note: str | None = None


class RecipeSearchPort(Protocol):
    """The part of `SearchService` that recipes and dispatch need."""

    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        """Return the top `k` hits for a query, best first."""
        ...

    def list_by_filter(
        self, filters: SearchFilters, cap: int
    ) -> list[SearchHit]:
        """Return up to `cap` chunks matching the filters, unranked."""
        ...
