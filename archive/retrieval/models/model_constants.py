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

DENSE_QUERY_PREFIX = ""
DENSE_PASSAGE_PREFIX = ""
DENSE_MAX_TOKENS: int | None = None
DENSE_EMBED_BATCH_SIZE = 32

LOG_MODEL_TIMEOUT = "Model %s not ready after %.0f s; continuing without it."
LOG_MODEL_FAILED = "Model %s failed to load: %s; continuing without it."
LOG_DIM_MISMATCH = "Dense model %s returned dimension %d, expected %d."
LOG_NO_TOKENIZER = (
    "Dense model %s exposes no tokenizer; keeping the default max length."
)
LOG_RERANK_DISABLED = "Reranker disabled; skipping model load."
