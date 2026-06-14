import pytest

from redraft.prompt import build_prompt, render


def test_render_substitutes_named_vars():
    assert render("hi <name>, in <where>", name="Al", where="Slack") == "hi Al, in Slack"


def test_render_leaves_unknown_placeholders_untouched():
    assert render("<message> and <unknown>", message="X") == "X and <unknown>"


def test_render_is_brace_safe():
    # Literal braces (JSON / {{R:n}} tokens) must survive untouched — the reason we don't use .format.
    tmpl = 'keep {{R:0}} and {"revised": string}; put <message>'
    assert render(tmpl, message="HI") == 'keep {{R:0}} and {"revised": string}; put HI'


def test_render_does_not_rescan_substituted_value():
    # A value containing <message> is inserted verbatim, not re-substituted.
    assert render("<message>", message="<message>") == "<message>"


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    # Resolve prompt overrides from an empty temp config dir, so these tests exercise the bundled
    # defaults (not whatever the developer has in ~/.config/redraft). Tests that want an override
    # write into tmp_path/redraft themselves.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "redraft").mkdir()
    return tmp_path / "redraft"


def test_fix_uses_fix_template():
    p = build_prompt("fix", "HELLO", {})
    assert "<message>" not in p  # placeholder spliced
    assert "HELLO" in p
    assert "smallest set" in p  # the fix template's wording


def test_improve_defaults_to_friendly():
    p = build_prompt("improve", "HELLO", {})
    assert "Slack" in p
    assert "HELLO" in p


def test_improve_formal_style():
    p = build_prompt("improve", "HELLO", {"improveStyle": "formal"})
    assert "email" in p.lower()


def test_unknown_style_falls_back_to_friendly():
    assert "Slack" in build_prompt("improve", "X", {"improveStyle": "nonsense"})


def test_config_dir_override_wins(isolated_config):
    (isolated_config / "friendly-prompt.txt").write_text("CUSTOM <message> END")
    assert build_prompt("improve", "ZZZ", {"improveStyle": "friendly"}) == "CUSTOM ZZZ END"


def test_template_without_placeholder_appends_message(isolated_config):
    (isolated_config / "fix-prompt.txt").write_text("NO PLACEHOLDER")
    p = build_prompt("fix", "ZZZ", {})
    assert p.startswith("NO PLACEHOLDER")
    assert "MESSAGE:\nZZZ" in p


def test_blank_override_falls_back_to_default(isolated_config):
    (isolated_config / "formal-prompt.txt").write_text("   \n  ")  # whitespace-only -> ignored
    assert "email" in build_prompt("improve", "X", {"improveStyle": "formal"}).lower()
