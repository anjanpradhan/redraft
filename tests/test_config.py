from redraft.config import load_config


def test_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "nope.json")
    assert cfg["fixProvider"] == "embedded"
    assert cfg["embedded"] == {"spell": False}
    assert cfg["improve"] == {"preFix": False}


def test_notification_defaults_present(tmp_path):
    # Spoon-only setting, but the engine config carries the defaults for documentation/seeding.
    cfg = load_config(tmp_path / "nope.json")
    assert cfg["notifications"] == {"fix": True, "improve": True, "status": True, "error": True}


def test_invalid_json_returns_defaults(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{ not valid json ")
    assert load_config(p)["improveProvider"] == "none"


def test_non_dict_subobjects_are_coerced(tmp_path):
    # L3: a malformed sub-object must not crash a provider with `'str'.get(...)`.
    p = tmp_path / "c.json"
    p.write_text('{"embedded": "yes", "ollama": 42, "agent": ["x"]}')
    cfg = load_config(p)
    assert cfg["embedded"] == {"spell": False}
    assert isinstance(cfg["ollama"], dict)
    assert isinstance(cfg["agent"], dict)


def test_user_values_merge_over_defaults(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"fixProvider": "languagetool", "ollama": {"model": "mistral"}}')
    cfg = load_config(p)
    assert cfg["fixProvider"] == "languagetool"
    assert cfg["ollama"]["model"] == "mistral"
    assert cfg["ollama"]["url"] == "http://localhost:11434"  # default preserved
