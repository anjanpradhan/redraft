import json

import pytest

from redraft.providers import languagetool, ollama


class _Resp:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, body):
        self._b = body.encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen(monkeypatch, fn):
    monkeypatch.setattr("urllib.request.urlopen", fn)


def test_ollama_timeout_is_friendly(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("read timed out")  # not a URLError subclass

    _urlopen(monkeypatch, boom)
    with pytest.raises(RuntimeError, match="cannot reach Ollama"):
        ollama.review("hi", "improve", {})


def test_ollama_non_json_body(monkeypatch):
    _urlopen(monkeypatch, lambda *a, **k: _Resp("<html>503</html>"))
    with pytest.raises(RuntimeError, match="non-JSON"):
        ollama.review("hi", "improve", {})


def test_ollama_happy_path(monkeypatch):
    body = json.dumps({"message": {"content": json.dumps({"revised": "OK"})}})
    _urlopen(monkeypatch, lambda *a, **k: _Resp(body))
    assert ollama.review("hi", "improve", {}).revised == "OK"


def test_languagetool_timeout_is_friendly(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("read timed out")

    _urlopen(monkeypatch, boom)
    with pytest.raises(RuntimeError, match="cannot reach LanguageTool"):
        languagetool.review("hi", "fix", {})


def test_languagetool_non_json_body(monkeypatch):
    _urlopen(monkeypatch, lambda *a, **k: _Resp("not json at all"))
    with pytest.raises(RuntimeError, match="non-JSON"):
        languagetool.review("hi", "fix", {})


def test_languagetool_applies_replacement(monkeypatch):
    body = json.dumps({"matches": [{"offset": 0, "length": 3, "replacements": [{"value": "The"}]}]})
    _urlopen(monkeypatch, lambda *a, **k: _Resp(body))
    assert languagetool.review("teh cat", "fix", {}).revised == "The cat"
