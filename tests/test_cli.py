import json
from unittest import mock

import pytest

from redraft import cli
from redraft.base import ReviewError


def _run(capsys, argv):
    rc = cli.main(argv)
    out = capsys.readouterr().out
    return rc, json.loads(out)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "redraft").mkdir()


def test_fix_via_input_file(tmp_path, capsys):
    f = tmp_path / "in.txt"
    f.write_text("i think teh `api` is down", encoding="utf-8")
    rc, data = _run(capsys, ["--mode", "fix", "--input", str(f)])
    assert rc == 0
    assert data["revised"].startswith("I think the ")
    assert "`api`" in data["revised"]


def test_missing_input_file_errors(capsys):
    rc, data = _run(capsys, ["--mode", "fix", "--input", "/no/such/file.txt"])
    assert rc == 1
    assert "cannot read input" in data["error"]


def test_non_utf8_input_errors_gracefully(tmp_path, capsys):
    # A selection that isn't valid UTF-8 must produce a clean JSON error, not a traceback.
    f = tmp_path / "bin.txt"
    f.write_bytes(b"\xff\xfe bad bytes")
    rc, data = _run(capsys, ["--mode", "fix", "--input", str(f)])
    assert rc == 1
    assert "cannot read input" in data["error"]


def test_empty_input_errors(tmp_path, capsys):
    f = tmp_path / "empty.txt"
    f.write_text("   \n", encoding="utf-8")
    rc, data = _run(capsys, ["--mode", "fix", "--input", str(f)])
    assert rc == 1
    assert data["error"] == "empty input"


def test_structured_review_error_includes_debug_context(tmp_path, capsys):
    f = tmp_path / "in.txt"
    f.write_text("ping `code`", encoding="utf-8")
    err = ReviewError(
        "output invariant violated (token {{R:0}} appears 0x, expected 1); leaving text unchanged",
        provider="agent",
        mode="improve",
        command="agent --run",
        prompt="sent prompt",
        raw='{"revised":"dropped"}',
    )
    with mock.patch("redraft.cli.review", side_effect=err):
        rc, data = _run(capsys, ["--mode", "improve", "--input", str(f)])

    assert rc == 1
    assert data["error"].startswith("output invariant violated")
    assert data["provider"] == "agent"
    assert data["mode"] == "improve"
    assert data["command"] == "agent --run"
    assert data["prompt"] == "sent prompt"
    assert data["raw"] == '{"revised":"dropped"}'
