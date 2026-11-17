"""Policy that bounds one run of the hop loop."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Self

from archive.agent.hops.hop_constants import (
    HOP_TIME_BUDGET_S,
    MULTI_HOP_MAX_DRAFTS,
    SAFETY_NET_MAX_DRAFTS,
)


@dataclass(frozen=True)
class HopPolicy:
    """Limits and options of the hop loop.

    Attributes:
        max_drafts: Most draft calls the loop may make.
        expand_upfront: Expand identifiers before the first draft.
        time_budget_s: No new draft starts once this has elapsed.
        clock: Monotonic time source, injectable for tests.
    """

    max_drafts: int
    expand_upfront: bool
    time_budget_s: float
    clock: Callable[[], float] = time.monotonic

    @classmethod
    def multi_hop(cls) -> Self:
        """Policy for multi-hop questions: expand, then loop."""
        return cls(
            max_drafts=MULTI_HOP_MAX_DRAFTS,
            expand_upfront=True,
            time_budget_s=HOP_TIME_BUDGET_S,
        )

    @classmethod
    def safety_net(cls) -> Self:
        """Policy for an insufficient first draft: one more hop."""
        return cls(
            max_drafts=SAFETY_NET_MAX_DRAFTS,
            expand_upfront=False,
            time_budget_s=HOP_TIME_BUDGET_S,
        )
