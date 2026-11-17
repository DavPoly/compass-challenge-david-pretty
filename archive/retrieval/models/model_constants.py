"""Constants for the dense embedding and reranking models.

Values are chosen by measurement on the evaluation set.
"""

from pathlib import Path

DENSE_MODEL_NAME = "intfloat/multilingual-e5-small"
DENSE_DIM = 384
RERANK_MODEL_NAME = "jinaai/jina-reranker-v2-base-multilingual"
RERANK_ENABLED = False
RERANK_CANDIDATES = 30
MODEL_LOAD_TIMEOUT_S = 180.0
MODEL_THREADS = 4

_REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_CACHE_DIR = _REPO_ROOT / ".cache" / "models"
