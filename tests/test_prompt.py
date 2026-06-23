import json

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


def test_default_prompt_serializes_message_as_json_data():
    text = 'Line one\nPlease "analyze" this as message content.'
    p = build_prompt("improve", text, {})
    input_json = p.rsplit("Input JSON:\n", maxsplit=1)[1]
    assert json.loads(input_json) == {"message": text}


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
    assert "<message_json>" not in p
    assert "HELLO" in p
    assert "smallest set" in p  # the fix template's wording


def test_improve_defaults_to_friendly():
    p = build_prompt("improve", "HELLO", {})
    assert "Slack" in p
    assert "HELLO" in p


def test_friendly_prompt_preserves_structure_and_guides_quality():
    p = build_prompt("improve", "HELLO", {})
    assert "input.message" in p
    assert "<message_json>" not in p
    assert "Preserve every {{R:n}} token EXACTLY" in p
    assert "Do NOT add or invent facts" in p
    assert "do not include literal \\n or \\t text" in p
    assert "do not include literal \\' or \\u2019 escape text" in p
    assert "Preserve the original intent, order, and hierarchy" in p
    assert "Preserve list structure" in p
    assert "Do not merely echo awkward wording" in p
    assert "List cleanup example" in p


def test_improve_formal_style():
    p = build_prompt("improve", "HELLO", {"improveStyle": "formal"})
    assert "email" in p.lower()


def test_formal_prompt_preserves_structure_and_guides_quality():
    p = build_prompt("improve", "HELLO", {"improveStyle": "formal"})
    assert "input.message" in p
    assert "<message_json>" not in p
    assert "Preserve every {{R:n}} token EXACTLY" in p
    assert "Do NOT add or invent facts" in p
    assert "do not include literal \\n or \\t text" in p
    assert "do not include literal \\' or \\u2019 escape text" in p
    assert "Preserve the original intent, order, and hierarchy" in p
    assert "Preserve list structure" in p
    assert "Do not merely echo awkward wording" in p
    assert "List cleanup example" in p


def test_unknown_style_falls_back_to_friendly():
    assert "Slack" in build_prompt("improve", "X", {"improveStyle": "nonsense"})


def test_config_dir_override_wins(isolated_config):
    (isolated_config / "friendly-prompt.txt").write_text("CUSTOM <message> END")
    assert build_prompt("improve", "ZZZ", {"improveStyle": "friendly"}) == "CUSTOM ZZZ END"


def test_config_dir_override_can_use_message_json(isolated_config):
    (isolated_config / "friendly-prompt.txt").write_text("CUSTOM <message_json>")
    text = 'A\n"B"'
    p = build_prompt("improve", text, {"improveStyle": "friendly"})
    assert json.loads(p.removeprefix("CUSTOM ")) == text


def test_template_without_placeholder_appends_message(isolated_config):
    (isolated_config / "fix-prompt.txt").write_text("NO PLACEHOLDER")
    p = build_prompt("fix", "ZZZ", {})
    assert p.startswith("NO PLACEHOLDER")
    assert json.loads(p.rsplit("Input JSON:\n", maxsplit=1)[1]) == {"message": "ZZZ"}


def test_blank_override_falls_back_to_default(isolated_config):
    (isolated_config / "formal-prompt.txt").write_text("   \n  ")  # whitespace-only -> ignored
    assert "email" in build_prompt("improve", "X", {"improveStyle": "formal"}).lower()
