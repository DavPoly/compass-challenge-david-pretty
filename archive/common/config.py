"""Application configuration read from the environment."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from archive.common.constants import (
    API_KEY_MASK,
    CACHE_DIR_NAME,
    CORPUS_DIR_NAME,
    ENV_LLM_API_KEY,
    ENV_LLM_BASE_URL,
    ENV_LLM_MODEL,
    INDEX_DIR_NAME,
    REPO_ROOT,
    TRACES_DIR_NAME,
    WEBAPP_DIR_NAME,
)

REQUIRED_ENV_VARS = (ENV_LLM_BASE_URL, ENV_LLM_API_KEY, ENV_LLM_MODEL)


class ConfigError(Exception):
    """Raised when required configuration is missing."""


@dataclass(frozen=True, repr=False)
class AppConfig:
    """Runtime settings. The API key is masked in `repr`."""

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    corpus_dir: Path
    index_dir: Path
    traces_dir: Path = field(
        default_factory=lambda: REPO_ROOT / TRACES_DIR_NAME
    )
    webapp_dir: Path = field(
        default_factory=lambda: REPO_ROOT / CACHE_DIR_NAME / WEBAPP_DIR_NAME
    )

    def __repr__(self) -> str:
        return (
            f"AppConfig(llm_base_url={self.llm_base_url!r}, "
            f"llm_api_key={API_KEY_MASK!r}, "
            f"llm_model={self.llm_model!r}, "
            f"corpus_dir={self.corpus_dir!r}, "
            f"index_dir={self.index_dir!r}, "
            f"traces_dir={self.traces_dir!r}, "
            f"webapp_dir={self.webapp_dir!r})"
        )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AppConfig":
        """Build the config from `LLM_*` variables.

        Raises:
            ConfigError: listing every missing or empty variable.
        """
        env = os.environ if environ is None else environ
        missing = [name for name in REQUIRED_ENV_VARS if not env.get(name, "")]
        if missing:
            fixes = "; ".join(f"export {name}=..." for name in missing)
            raise ConfigError(
                f"Missing environment variables: {', '.join(missing)}. "
                f"Set them before running ({fixes})."
            )
        return cls(
            llm_base_url=env[ENV_LLM_BASE_URL],
            llm_api_key=env[ENV_LLM_API_KEY],
            llm_model=env[ENV_LLM_MODEL],
            corpus_dir=REPO_ROOT / CORPUS_DIR_NAME,
            index_dir=REPO_ROOT / INDEX_DIR_NAME,
            traces_dir=REPO_ROOT / TRACES_DIR_NAME,
            webapp_dir=REPO_ROOT / CACHE_DIR_NAME / WEBAPP_DIR_NAME,
        )
