import pytest

from archive.common.config import AppConfig, ConfigError

SECRET = "sk-super-secret"
VALID_ENV = {
    "LLM_BASE_URL": "http://localhost",
    "LLM_API_KEY": SECRET,
    "LLM_MODEL": "model",
}


def test_from_env_reads_variables() -> None:
    config = AppConfig.from_env(VALID_ENV)
    assert config.llm_model == "model"
    assert config.corpus_dir.name == "corpus"
    assert config.index_dir.name == "index"
    assert config.traces_dir.name == "traces"
    assert config.webapp_dir.name == "webapp"


def test_missing_variables_are_all_listed() -> None:
    with pytest.raises(ConfigError) as error:
        AppConfig.from_env({})
    message = str(error.value)
    for name in VALID_ENV:
        assert f"export {name}=" in message


def test_only_missing_variable_is_named_and_key_not_leaked() -> None:
    env = {k: v for k, v in VALID_ENV.items() if k != "LLM_MODEL"}
    with pytest.raises(ConfigError) as error:
        AppConfig.from_env(env)
    message = str(error.value)
    assert "LLM_MODEL" in message
    assert "LLM_BASE_URL" not in message
    assert SECRET not in message


def test_empty_value_counts_as_missing() -> None:
    with pytest.raises(ConfigError, match="LLM_MODEL"):
        AppConfig.from_env({**VALID_ENV, "LLM_MODEL": ""})


def test_repr_masks_api_key() -> None:
    config = AppConfig.from_env(VALID_ENV)
    assert SECRET not in repr(config)
    assert SECRET not in str(config)
