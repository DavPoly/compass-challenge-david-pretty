"""Constants of the search service."""

UNRANKED_SCORE = 0.0
# How long teardown waits for an in-flight query before closing the
# index anyway: a stuck worker must never hang the run.
QUERY_DRAIN_TIMEOUT_S = 3.0
LOG_CLOSE_TIMEOUT = (
    "index closed after %.0f s without the read lock; a query may "
    "still have been running"
)
