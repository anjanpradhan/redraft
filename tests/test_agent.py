import pytest

from redraft.providers import agent


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    # Make resolution hermetic: ignore any real agent CLIs installed on the dev machine, so
    # only the explicit `agent.bins` hints in each test resolve. (Keeps real PATH for /bin/sh.)
    monkeypatch.setattr(agent, "_KNOWN_DIRS", [])
    monkeypatch.setattr(agent.shutil, "which", lambda _name: None)


def _fake_agent(tmp_path, name, revised):
    """Create an executable that ignores stdin and prints a JSON ReviewResult."""
    p = tmp_path / name
    p.write_text(f'#!/bin/sh\ncat >/dev/null\nprintf \'{{"revised":"{revised}"}}\'\n')
    p.chmod(0o755)
    return str(p)


def test_resolve_bin_uses_configured_hint(tmp_path):
    fake = _fake_agent(tmp_path, "claude", "x")
    cfg = {"agent": {"bins": {"claude": fake}}}
    assert agent.resolve_bin("claude", cfg) == fake


def test_resolve_bin_none_when_missing():
    assert agent.resolve_bin("gemini", {"agent": {"bins": {}}}) is None
    assert agent.resolve_bin("nonsuch", {}) is None


def test_auto_honors_preference_order(tmp_path):
    # both gemini and claude available -> claude wins (earlier in PREFERENCE)
    cfg = {"agent": {"tool": "auto", "bins": {
        "gemini": _fake_agent(tmp_path, "gemini", "GEM"),
        "claude": _fake_agent(tmp_path, "claude", "CLA"),
    }}}
    assert agent.review("hi", "improve", cfg).revised == "CLA"


def test_auto_falls_through_to_next_available(tmp_path):
    cfg = {"agent": {"tool": "auto", "bins": {"gemini": _fake_agent(tmp_path, "gemini", "GEM")}}}
    out = agent.review("hi", "improve", cfg)
    assert out.revised == "GEM"
    assert "via gemini" in out.change_notes


def test_explicit_tool(tmp_path):
    cfg = {"agent": {"tool": "codex", "bins": {"codex": _fake_agent(tmp_path, "codex", "CDX")}}}
    assert agent.review("hi", "improve", cfg).revised == "CDX"


def test_template_override(tmp_path):
    fake = _fake_agent(tmp_path, "mygemini", "OVR")
    cfg = {"agent": {"tool": "gemini", "bins": {"gemini": fake}, "commands": {"gemini": "{bin}"}}}
    assert agent.review("hi", "improve", cfg).revised == "OVR"


def test_no_agent_found_raises():
    with pytest.raises(RuntimeError, match="no agent CLI found"):
        agent.review("hi", "improve", {"agent": {"tool": "auto", "bins": {}}})


def test_unknown_tool_raises():
    with pytest.raises(RuntimeError, match="unknown agent"):
        agent.review("hi", "improve", {"agent": {"tool": "bogus"}})


def test_default_commands_cover_all_agents():
    # Single source of truth the installer seeds into config.agent.commands.
    d = agent.default_commands()
    assert set(d) == set(agent.AGENTS)
    assert "$(cat)" not in "\n".join(d.values())
    assert "{prompt_file}" in d["claude"]
    assert "--skip-git-repo-check" in d["codex"]
    assert "{prompt_file}" in d["codex"]
    assert "{prompt_file}" in d["gemini"]
    assert "{prompt_arg}" in d["copilot"]


def test_config_command_overrides_default_template(tmp_path):
    fake = _fake_agent(tmp_path, "codex", "OVR")
    cfg = {"agent": {"tool": "codex", "bins": {"codex": fake}, "commands": {"codex": "{bin}"}}}
    assert agent.review("hi", "improve", cfg).revised == "OVR"
