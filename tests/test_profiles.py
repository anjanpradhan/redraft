import pytest

from redraft.engine import review
from redraft.providers import agent, command, embedded, languagetool, ollama, pick_provider

SLACK = "com.tinyspeck.slackmacgap"


def test_profile_overrides_provider_for_app():
    cfg = {"fixProvider": "embedded", "profiles": {SLACK: {"fixProvider": "languagetool"}}}
    assert pick_provider("fix", cfg, SLACK) is languagetool
    # improve key not set in the profile -> falls back to the global (default "embedded" path)
    assert pick_provider("fix", cfg, None) is embedded


def test_profile_falls_back_when_key_missing():
    # profile sets only improveProvider, so fix still resolves globally
    cfg = {
        "fixProvider": "embedded",
        "improveProvider": "ollama",
        "profiles": {SLACK: {"improveProvider": "command"}},
    }
    assert pick_provider("fix", cfg, SLACK) is embedded
    assert pick_provider("improve", cfg, SLACK) is command
    assert pick_provider("improve", cfg, None) is ollama


def test_unknown_app_uses_global():
    cfg = {"fixProvider": "languagetool", "profiles": {SLACK: {"fixProvider": "embedded"}}}
    assert pick_provider("fix", cfg, "com.example.other") is languagetool


def test_malformed_profiles_are_ignored():
    assert pick_provider("fix", {"profiles": "nope"}, SLACK) is embedded
    assert pick_provider("fix", {"profiles": {SLACK: "nope"}}, SLACK) is embedded


def test_profile_none_provider_raises():
    cfg = {"improveProvider": "ollama", "profiles": {SLACK: {"improveProvider": "none"}}}
    with pytest.raises(RuntimeError, match="not configured"):
        pick_provider("improve", cfg, SLACK)


def test_provider_modes_are_enforced():
    with pytest.raises(RuntimeError, match="not available for improve"):
        pick_provider("improve", {"improveProvider": "languagetool"})
    with pytest.raises(RuntimeError, match="not available for fix"):
        pick_provider("fix", {"fixProvider": "agent"})
    assert pick_provider("improve", {"improveProvider": "agent"}) is agent


def test_engine_routes_by_app():
    cfg = {"fixProvider": "embedded", "profiles": {SLACK: {"fixProvider": "embedded"}}}
    out = review("teh cat", "fix", cfg, app=SLACK)
    assert out["revised"].startswith("The cat")
    assert out["provider"] == "embedded"
