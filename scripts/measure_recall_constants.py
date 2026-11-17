"""Constants of the recall measurement script."""

DEFAULT_GOLD_PARTS = ("samples", "gold.jsonl")
DEFAULT_KS = "8,12,16,24,32"
ID_WIDTH = 6
CELL_WIDTH = 9
MSG_DENSE_UNAVAILABLE = (
    "Dense model unavailable; measuring sparse-only recall."
)
MSG_RERANK_UNAVAILABLE = (
    "Reranker unavailable; measuring recall without reranking."
)
RERANK_GATE_ATTR = "RERANK_ENABLED"
