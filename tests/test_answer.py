from pathlib import Path

import pytest

import answer
from archive.pipeline.pipeline_constants import EXIT_ERROR, EXIT_USAGE

LLM_VARS = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")


@pytest.mark.parametrize("argv", [[], ["only_one.jsonl"], ["a", "b", "c"]])
def test_wrong_argument_count_is_a_usage_error(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert answer.main(argv) == EXIT_USAGE
    assert "usage" in capsys.readouterr().err


def test_missing_env_vars_exit_one_naming_each(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in LLM_VARS:
        monkeypatch.delenv(name, raising=False)

    code = answer.main([str(tmp_path / "q.jsonl"), str(tmp_path / "a.jsonl")])

    error = capsys.readouterr().err
    assert code == EXIT_ERROR
    assert all(name in error for name in LLM_VARS)


def test_exit_now_flushes_everything_before_the_hard_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        answer.logging, "shutdown", lambda: calls.append("log")
    )
    monkeypatch.setattr(
        answer.sys.stdout, "flush", lambda: calls.append("out")
    )
    monkeypatch.setattr(
        answer.sys.stderr, "flush", lambda: calls.append("err")
    )
    monkeypatch.setattr(answer.os, "_exit", calls.append)

    answer.exit_now(EXIT_ERROR)

    assert calls == ["log", "out", "err", EXIT_ERROR]
