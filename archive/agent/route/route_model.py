"""Question plan: the family of a question and its extracted filters."""

from enum import StrEnum

from pydantic import BaseModel, Field

from archive.agent.route.route_constants import (
    AS_OF_DATE_DESCRIPTION,
    CLIENT_DESCRIPTION,
    DATE_FROM_DESCRIPTION,
    DATE_TO_DESCRIPTION,
    FAMILY_DESCRIPTION,
    MEASURE_DESCRIPTION,
    POLICY_TOPIC_DESCRIPTION,
    PROJECT_CODES_DESCRIPTION,
    PROJECT_MANAGER_DESCRIPTION,
)


class QuestionFamily(StrEnum):
    """How a question is answered."""

    DIRECT = "direct"
    AGGREGATION = "aggregation"
    SUPERSEDED = "superseded"
    MULTI_HOP = "multi_hop"


class AmountMeasure(StrEnum):
    """Which invoice amount an aggregation sums."""

    PRE_TAX = "pre_tax"
    TAX_INCLUDED = "tax_included"


class QuestionPlan(BaseModel):
    """The routing decision and filters extracted from a question."""

    family: QuestionFamily = Field(description=FAMILY_DESCRIPTION)
    client: str | None = Field(None, description=CLIENT_DESCRIPTION)
    project_manager: str | None = Field(
        None, description=PROJECT_MANAGER_DESCRIPTION
    )
    project_codes: list[str] = Field(
        default_factory=list, description=PROJECT_CODES_DESCRIPTION
    )
    date_from: str | None = Field(None, description=DATE_FROM_DESCRIPTION)
    date_to: str | None = Field(None, description=DATE_TO_DESCRIPTION)
    as_of_date: str | None = Field(None, description=AS_OF_DATE_DESCRIPTION)
    measure: AmountMeasure | None = Field(
        None, description=MEASURE_DESCRIPTION
    )
    policy_topic: str | None = Field(
        None, description=POLICY_TOPIC_DESCRIPTION
    )
