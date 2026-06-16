import json

import pytest

from redraft import cli


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
