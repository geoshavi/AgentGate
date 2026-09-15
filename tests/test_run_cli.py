"""`engine run`: the setup-failure path reports cleanly instead of tracebacking.

Offline: no API key is set and no provider call happens. Building the
Anthropic provider fails fast on a missing key (``providers/registry.py``),
which is exactly the failure this test exercises.
"""

import sys
from pathlib import Path

import pytest

from engine import cli


def test_missing_api_key_reports_a_clean_error_and_exits_nonzero(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ENGINE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["engine", "run", "add two numbers", "--workspace", str(tmp_path / "ws")],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code != 0
    captured = capsys.readouterr()
    assert captured.err.strip() == "ERROR: ValueError: ANTHROPIC_API_KEY is not set"
    # No raw traceback: none of Python's traceback markers reach the user.
    assert "Traceback (most recent call last)" not in captured.out
    assert "Traceback (most recent call last)" not in captured.err
