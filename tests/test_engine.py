import types
from pathlib import Path
from unittest import mock

import pytest

from redraft.base import ReviewResult
from redraft.engine import review


def test_fix_embedded_preserves_protected():
    out = review("i think the `api` is down, see http://x.io", "fix", {"fixProvider": "embedded"})
    assert "`api`" in out["revised"]
    assert "http://x.io" in out["revised"]
    assert out["revised"].startswith("I think the ")  # i->I, the->the, start-capped
    assert out["provider"] == "embedded"


def test_unknown_mode_raises():
    with pytest.raises(RuntimeError):
        review("x", "bogus", {})


def test_improve_none_raises():
    with pytest.raises(RuntimeError):
        review("x", "improve", {"improveProvider": "none"})


def test_invariant_violation_rejected():
    # a provider that drops the protected token must cause a refusal
    fake = types.SimpleNamespace(
        __name__="redraft.providers.fake",
        review=lambda _text, _mode, _config: ReviewResult(revised="dropped the token"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake), pytest.raises(RuntimeError, match="invariant"):
        review("ping `code`", "improve", {})


def test_llm_invariant_retry_rescues():
    # An LLM provider (sets .prompt) that drops the token once, then echoes it, is resampled and saved.
    calls = {"n": 0}

    def flaky(_text, _mode, _config):
        calls["n"] += 1
        revised = "dropped the token" if calls["n"] == 1 else "kept {{R:0}}"
        return ReviewResult(revised=revised, prompt="sent")

    fake = types.SimpleNamespace(__name__="redraft.providers.fake", review=flaky)
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review("ping `code`", "improve", {})
    assert "`code`" in out["revised"]  # restored after the rescuing retry
    assert calls["n"] == 2  # original call + one retry


def test_llm_invariant_retry_exhausted_raises():
    # An LLM provider that drops the token on every sample still fails after the bounded retry.
    calls = {"n": 0}

    def always_drops(_text, _mode, _config):
        calls["n"] += 1
        return ReviewResult(revised="dropped the token", prompt="sent")

    fake = types.SimpleNamespace(__name__="redraft.providers.fake", review=always_drops)
    with mock.patch("redraft.engine.pick_provider", return_value=fake), pytest.raises(RuntimeError, match="invariant"):
        review("ping `code`", "improve", {})
    assert calls["n"] == 2  # original + one retry, then gives up


def test_deterministic_invariant_failure_not_retried():
    # A provider with no .prompt (deterministic-style) is never resampled — it fails on the first call.
    calls = {"n": 0}

    def drops_no_prompt(_text, _mode, _config):
        calls["n"] += 1
        return ReviewResult(revised="dropped the token")  # prompt stays None

    fake = types.SimpleNamespace(__name__="redraft.providers.fake", review=drops_no_prompt)
    with mock.patch("redraft.engine.pick_provider", return_value=fake), pytest.raises(RuntimeError, match="invariant"):
        review("ping `code`", "improve", {})
    assert calls["n"] == 1  # no retry for a deterministic provider


def test_literal_token_round_trips_through_engine():
    # M2: a user typing {{R:0}} must NOT trigger a false "token invariant violated" — it round-trips.
    out = review("note {{R:0}} stays", "fix", {"fixProvider": "embedded"})
    assert "{{R:0}}" in out["revised"]


def test_engine_includes_command_for_shell_provider():
    cfg = {"fixProvider": "command", "command": {"cmd": 'printf \'{"revised":"ok"}\''}}
    out = review("hi", "fix", cfg)
    assert out["command"] == 'printf \'{"revised":"ok"}\''


def test_engine_omits_command_for_in_process_provider():
    out = review("hi", "fix", {"fixProvider": "embedded"})
    assert "command" not in out  # only shell providers report a command
    assert "prompt" not in out  # deterministic providers have no prompt


def test_engine_includes_prompt_for_shell_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # isolate from any real prompt overrides
    # The command must echo the protected token back or the invariant rejects it.
    cfg = {"fixProvider": "command", "command": {"cmd": 'printf \'{"revised":"ok {{R:0}}"}\''}}
    out = review("ping `code`", "fix", cfg)
    # The reported prompt is what the model saw: the protected projection ({{R:0}} for `code`),
    # spliced into the fix template's <message> slot.
    assert "{{R:0}}" in out["prompt"]
    assert "MESSAGE:" in out["prompt"]


def test_engine_includes_raw_response_for_shell_provider():
    # The raw response is the CLI's full stdout, before JSON extraction / token restoration.
    cfg = {"fixProvider": "command", "command": {"cmd": 'printf \'chatter {"revised":"ok"}\''}}
    out = review("hi", "fix", cfg)
    assert out["raw"] == 'chatter {"revised":"ok"}'
    assert out["revised"] == "ok"  # extraction/restoration still produce the clean result


def test_provider_passthrough_ok():
    fake = types.SimpleNamespace(
        __name__="redraft.providers.fake",
        review=lambda text, _mode, _config: ReviewResult(revised=text, change_notes=["noop"]),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review("ping `code`", "improve", {})
        assert "`code`" in out["revised"]
        assert out["change_notes"] == ["noop"]


def test_improve_does_not_prefix_by_default():
    seen: dict[str, str] = {}

    def fake_review(text: str, _mode: str, _config: dict) -> ReviewResult:
        seen["text"] = text
        return ReviewResult(revised=text)

    fake = types.SimpleNamespace(
        __name__="redraft.providers.fake",
        review=fake_review,
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review("i think teh `api` is down", "improve", {})
    assert seen["text"].startswith("i think teh ")
    assert out["revised"].startswith("i think teh ")


def test_improve_prefix_runs_embedded_before_provider():
    seen: dict[str, str] = {}

    def fake_review(text: str, _mode: str, _config: dict) -> ReviewResult:
        seen["text"] = text
        return ReviewResult(revised=text, change_notes=["improved"])

    fake = types.SimpleNamespace(__name__="redraft.providers.fake", review=fake_review)
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review("i think teh `api` is down", "improve", {"improve": {"preFix": True}})
    assert seen["text"].startswith("I think the ")
    assert "{{R:0}}" in seen["text"]
    assert out["revised"].startswith("I think the ")
    assert "`api`" in out["revised"]
    assert out["change_notes"][:2] == ["pre-fix: i → I", "pre-fix: teh → the"]
    assert out["change_notes"][-1] == "improved"
