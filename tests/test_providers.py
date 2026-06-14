import pytest

from redraft.prompt import build_result, extract_json
from redraft.providers import _shell, command

# --- extract_json: must return the FIRST balanced object, string-aware -----------------------


def test_extract_json_first_balanced_object():
    assert extract_json('noise {"revised":"a"} chatter {"x":1} tail') == '{"revised":"a"}'


def test_extract_json_handles_braces_inside_strings():
    assert extract_json('pre {"revised":"a}b{c"} post') == '{"revised":"a}b{c"}'


def test_extract_json_none_when_absent():
    assert extract_json("no json here") is None


# --- build_result: notes/flags must be list[str], not coerced from a bare string ----------------


def test_build_result_requires_revised_str():
    with pytest.raises(RuntimeError):
        build_result({"revised": 123}, "x")
    with pytest.raises(RuntimeError):
        build_result(["not", "a", "dict"], "x")


def test_build_result_coerces_notes_and_flags():
    # a bare string must NOT become a char list; non-list -> []
    r = build_result({"revised": "ok", "change_notes": "fixed typo", "risk_flags": None}, "x")
    assert r.change_notes == []
    assert r.risk_flags == []
    # a proper list is kept, elements stringified
    r = build_result({"revised": "ok", "change_notes": ["a", 2]}, "x")
    assert r.change_notes == ["a", "2"]


# --- command provider: Fix and Improve can use different CLIs ------------------------------------


def test_command_per_mode_commands():
    cfg = {"command": {"fixCmd": 'printf \'{"revised":"FIX"}\'', "improveCmd": 'printf \'{"revised":"IMP"}\''}}
    assert command.review("hi", "fix", cfg).revised == "FIX"
    assert command.review("hi", "improve", cfg).revised == "IMP"


def test_command_falls_back_to_shared_cmd():
    cfg = {"command": {"cmd": 'printf \'{"revised":"SHARED"}\''}}
    assert command.review("hi", "fix", cfg).revised == "SHARED"
    assert command.review("hi", "improve", cfg).revised == "SHARED"


def test_command_unconfigured_raises():
    with pytest.raises(RuntimeError, match="not configured"):
        command.review("hi", "fix", {"command": {}})


def test_command_surfaces_resolved_command():
    cmd = 'printf \'{"revised":"X"}\''
    r = command.review("hi", "fix", {"command": {"cmd": cmd}})
    assert r.command == cmd  # no prompt placeholder, so the display matches the configured command


def test_command_error_includes_command():
    # A failing command embeds the command display in the error so the user can see what ran.
    with pytest.raises(RuntimeError, match="command: false"):
        command.review("hi", "fix", {"command": {"cmd": "false"}})


def test_command_error_includes_long_stderr():
    # stderr well past the old 200-char cap is surfaced (shown in the copyable error modal).
    cmd = "printf '%s' " + ("E" * 500) + " >&2; exit 1"
    with pytest.raises(RuntimeError) as ei:
        command.review("hi", "fix", {"command": {"cmd": cmd}})
    assert "E" * 400 in str(ei.value)


def test_shell_prompt_file_placeholder_redacts_command():
    cmd = 'wc -c < {prompt_file} >/dev/null; printf \'{"revised":"OK"}\''
    r = _shell.run(cmd, "SENSITIVE", 1000, "x")
    assert r.revised == "OK"
    assert "<prompt-file>" in r.command
    assert "SENSITIVE" not in r.command
    assert r.prompt == "SENSITIVE"


def test_shell_prompt_arg_placeholder_redacts_command():
    cmd = 'printf %s {prompt_arg} >/dev/null; printf \'{"revised":"OK"}\''
    r = _shell.run(cmd, "SENSITIVE", 1000, "x")
    assert r.revised == "OK"
    assert "<prompt>" in r.command
    assert "SENSITIVE" not in r.command
