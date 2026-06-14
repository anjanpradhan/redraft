import io
import json
import urllib.error
from typing import Never

import pytest

from redraft.providers import languagetool, ollama


class _Resp:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, body) -> None:
        self._b = body.encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen(monkeypatch, fn) -> None:
    monkeypatch.setattr("urllib.request.urlopen", fn)


def test_ollama_timeout_is_friendly(monkeypatch):
    def boom(*a, **k) -> Never:
        raise TimeoutError("read timed out")  # not a URLError subclass

    _urlopen(monkeypatch, boom)
    with pytest.raises(RuntimeError, match="cannot reach Ollama"):
        ollama.review("hi", "improve", {})


def test_ollama_missing_model_is_actionable(monkeypatch):
    # A 404 from a reachable server means the model isn't pulled — say so (with the fix), not the
    # misleading "is serve running?" hint.
    def http_404(*a, **k) -> Never:
        raise urllib.error.HTTPError(
            "http://x/api/chat", 404, "Not Found", {}, io.BytesIO(b'{"error":"model not found"}')
        )

    _urlopen(monkeypatch, http_404)
    with pytest.raises(RuntimeError, match=r"ollama pull llama3.2:3b"):
        ollama.review("hi", "improve", {"ollama": {"model": "llama3.2:3b"}})


def test_ollama_non_json_body(monkeypatch):
    _urlopen(monkeypatch, lambda *a, **k: _Resp("<html>503</html>"))
    with pytest.raises(RuntimeError, match="non-JSON"):
        ollama.review("hi", "improve", {})


def test_ollama_happy_path(monkeypatch):
    body = json.dumps({"message": {"content": json.dumps({"revised": "OK"})}})
    _urlopen(monkeypatch, lambda *a, **k: _Resp(body))
    assert ollama.review("hi", "improve", {}).revised == "OK"


def test_languagetool_timeout_is_friendly(monkeypatch):
    def boom(*a, **k) -> Never:
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
