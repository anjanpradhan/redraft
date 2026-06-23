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
    # spliced into the fix template's JSON message slot.
    assert "{{R:0}}" in out["prompt"]
    assert "Input JSON:" in out["prompt"]


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


def test_llm_provider_gets_real_line_breaks_and_restores():
    text = "Of course.\nAnyway, I'm not doing anything in the coming sprint."
    seen: dict[str, str] = {}

    def fake_review(projection: str, _mode: str, _config: dict) -> ReviewResult:
        seen["projection"] = projection
        return ReviewResult(revised=projection, prompt="sent")

    fake = types.SimpleNamespace(__name__="redraft.providers.agent", review=fake_review)
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert seen["projection"] == text
    assert out["revised"] == text


def test_llm_provider_can_shorten_multiline_without_semantic_rejection():
    text = "Of course.\nAnyway, I'm not doing anything in the coming sprint."

    def fake_review(_projection: str, _mode: str, _config: dict) -> ReviewResult:
        return ReviewResult(revised="Of course.", prompt="sent")

    fake = types.SimpleNamespace(__name__="redraft.providers.agent", review=fake_review)
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == "Of course."


def test_llm_provider_can_collapse_line_break_when_content_survives():
    text = "Of course.\nAnyway, I'm not doing anything in the coming sprint."
    revised = "Of course. Anyway, I'm not doing anything in the coming sprint."

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == revised


def test_llm_provider_can_rephrase_multiline_tail_when_content_survives():
    text = "Of course.\nAnyway, I'm not doing anything in the coming sprint."
    revised = "Sure. I won't be involved in the sprint."

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == revised


def test_llm_provider_can_absorb_short_context_lines():
    text = "It would be a message on Slack.\nI would like warmer tone with professionalism and gratutude."
    revised = "I'd like it to sound warmer and more professional, with gratitude."

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == revised


def test_llm_provider_content_free_output_is_not_semantically_rejected():
    text = "It would be a message on Slack.\nI would like warmer tone with professionalism and gratutude."

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised="OK.", prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == "OK."


def test_llm_provider_literal_escaped_newlines_become_real_newlines():
    text = "use recs-platform when was npp last refreshed?\nuse recs-platform why is the badge missing?"
    revised = "Use recs-platform when was npp last refreshed?\\nUse recs-platform why is the badge missing?"

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == revised.replace("\\n", "\n")


def test_llm_provider_mixed_escaped_newlines_become_real_when_matching_shape():
    text = "Plan:\n- existing components\n- new components\n\nFirst analyze.\nAsk questions."
    revised = "Plan:\\n- existing components\\n- new components\n\nFirst analyze.\nAsk questions."

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == revised.replace("\\n", "\n")


def test_llm_provider_preserves_literal_backslash_n_when_shape_is_not_improved():
    text = "Use literal \\n in docs.\nThen continue."
    revised = "Use literal \\n in docs.\nThen continue."

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == revised


def test_llm_provider_escaped_tabs_become_spaces_when_not_source_content():
    text = "Plan:\n- existing components\n- new components"
    revised = "Plan:\n\\t- existing components\n\\t- new components"

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == "Plan:\n  - existing components\n  - new components"


def test_llm_provider_escaped_tabs_restore_real_tabs_when_original_uses_tabs():
    text = "Name\tValue\nalpha\t1"
    revised = "Name\\tValue\nalpha\\t1"

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == text


def test_llm_provider_preserves_literal_backslash_t_when_original_has_it():
    text = "Use literal \\t in docs.\nThen continue."
    revised = "Use literal \\t in docs.\nThen continue."

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == revised


def test_llm_provider_escaped_apostrophes_are_repaired():
    text = "I'll do it.\nDon't wait."
    revised = "I\\'ll do it.\nDon\\u0027t wait."

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == "I'll do it.\nDon't wait."


def test_llm_provider_unicode_escapes_decode_to_unicode_punctuation():
    text = 'He said, "Do not wait - really..."'
    revised = "He said, \\u201cDon\\u2019t wait\\u2014really\\u2026\\u201d"

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == "He said, \u201cDon\u2019t wait\u2014really\u2026\u201d"


def test_llm_provider_preserves_literal_prose_escapes_when_original_has_them():
    text = "Use literal \\u2019 and \\' in docs."
    revised = "Use literal \\u2019 and \\' in docs."

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == revised


def test_llm_provider_restores_original_paragraph_separators_when_line_count_matches():
    text = (
        "use recs-platform when was npp last refreshed?\n"
        "use recs-platform why is the badge missing?\n\n"
        "use recs-platform where are FBT recommendations dropped?"
    )
    revised = (
        "Use recs-platform when was npp last refreshed?\\n"
        "Use recs-platform why is the badge missing?\\n"
        "Use recs-platform where are FBT recommendations dropped?"
    )

    fake = types.SimpleNamespace(
        __name__="redraft.providers.agent",
        review=lambda _projection, _mode, _config: ReviewResult(revised=revised, prompt="sent"),
    )
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == (
        "Use recs-platform when was npp last refreshed?\n"
        "Use recs-platform why is the badge missing?\n\n"
        "Use recs-platform where are FBT recommendations dropped?"
    )


def test_improve_runs_embedded_fix_before_provider_by_default():
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
    assert seen["text"].startswith("I think the ")
    assert "{{R:0}}" in seen["text"]
    assert out["revised"].startswith("I think the ")
    assert "`api`" in out["revised"]


def test_improve_fix_step_notes_are_reported_before_provider_notes():
    seen: dict[str, str] = {}

    def fake_review(text: str, _mode: str, _config: dict) -> ReviewResult:
        seen["text"] = text
        return ReviewResult(revised=text, change_notes=["improved"])

    fake = types.SimpleNamespace(__name__="redraft.providers.fake", review=fake_review)
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review("i think teh `api` is down", "improve", {})
    assert seen["text"].startswith("I think the ")
    assert "{{R:0}}" in seen["text"]
    assert out["revised"].startswith("I think the ")
    assert "`api`" in out["revised"]
    assert out["change_notes"][:2] == ["pre-fix: i → I", "pre-fix: teh → the"]
    assert out["change_notes"][-1] == "improved"


def test_improve_fix_step_updates_multiline_structure_baseline():
    text = "teh enviroment\nadn recieve"

    def echo_pre_fixed(projection: str, _mode: str, _config: dict) -> ReviewResult:
        return ReviewResult(revised=projection, prompt="sent")

    fake = types.SimpleNamespace(__name__="redraft.providers.agent", review=echo_pre_fixed)
    with mock.patch("redraft.engine.pick_provider", return_value=fake):
        out = review(text, "improve", {})

    assert out["revised"] == "The environment\nand receive"
