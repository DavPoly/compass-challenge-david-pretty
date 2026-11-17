import pytest

from archive.pipeline import run_service


@pytest.fixture(autouse=True)
def no_model_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never load (or download) a model unless a test installs a fake."""
    monkeypatch.setattr(run_service, "load_embedder", lambda timeout_s: None)
    monkeypatch.setattr(run_service, "load_reranker", lambda timeout_s: None)
