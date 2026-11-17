import pytest

from archive.common import config as config_module
from archive.pipeline import run_service


@pytest.fixture(autouse=True)
def no_model_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never load (or download) a model unless a test installs a fake."""
    monkeypatch.setattr(run_service, "load_embedder", lambda timeout_s: None)
    monkeypatch.setattr(run_service, "load_reranker", lambda timeout_s: None)


@pytest.fixture(autouse=True)
def isolated_repo_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Default trace and viewer dirs never point into the real repo."""
    root = tmp_path_factory.mktemp("repo_root")
    monkeypatch.setattr(config_module, "REPO_ROOT", root)
