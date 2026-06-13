from redraft.protect import check_invariant, protect, restore


def test_protects_code_and_urls():
    proj, spans = protect("run `kubectl get pods` then open https://ex.io/x and ping")
    assert "`kubectl get pods`" not in proj
    assert "https://ex.io/x" not in proj
    assert len(spans) == 2
    assert "{{R:0}}" in proj
    assert "{{R:1}}" in proj


def test_restore_round_trips():
    text = "see `code` at https://a.b/c end"
    proj, spans = protect(text)
    assert restore(proj, spans) == text


def test_invariant_ok():
    ok, reason = check_invariant(2, "x {{R:0}} y {{R:1}}")
    assert ok
    assert reason is None


def test_invariant_allows_reorder():
    ok, _ = check_invariant(2, "{{R:1}} then {{R:0}}")
    assert ok


def test_invariant_rejects_dropped():
    ok, _ = check_invariant(2, "only {{R:0}}")
    assert not ok


def test_invariant_rejects_duplicate():
    ok, _ = check_invariant(1, "{{R:0}} {{R:0}}")
    assert not ok


def test_invariant_rejects_unknown():
    ok, _ = check_invariant(1, "{{R:0}} {{R:5}}")
    assert not ok


def test_literal_token_is_protected_and_round_trips():
    # M2: a literal {{R:n}} the user typed must round-trip, not collide with our namespace.
    text = "I wrote {{R:0}} and `code` in {{R:7}}"
    proj, spans = protect(text)
    assert len(spans) == 3  # two literal tokens + one code span
    ok, _ = check_invariant(len(spans), proj)
    assert ok
    assert restore(proj, spans) == text


def test_url_excludes_trailing_punctuation():
    # L4: a comma/period after a URL stays in the prose, not glued into the protected span.
    proj, spans = protect("see https://ex.io/a, then https://ex.io/b.")
    assert spans == ["https://ex.io/a", "https://ex.io/b"]
    assert proj == "see {{R:0}}, then {{R:1}}."


# --- expanded protection heuristics: one positive case per new span type ----------------------


def _protected(text: str) -> list[str]:
    """Return the list of spans protect() pulled out of text."""
    return protect(text)[1]


def test_protects_markdown_link_whole():
    # The whole [text](url) is one span — the inner URL must NOT be split out separately.
    proj, spans = protect("click [the docs](https://ex.io/d) please")
    assert spans == ["[the docs](https://ex.io/d)"]
    assert proj == "click {{R:0}} please"


def test_protects_email():
    assert _protected("ping me@example.io now") == ["me@example.io"]


def test_protects_env_var():
    assert _protected("set $HOME and ${API_KEY} please") == ["$HOME", "${API_KEY}"]


def test_protects_paths():
    assert _protected("see ./src/app.py and ~/notes and /usr/local/bin tools") == [
        "./src/app.py",
        "~/notes",
        "/usr/local/bin",
    ]


def test_path_drops_trailing_sentence_period():
    # A path ending a sentence keeps its internal dots but releases the terminal period to the prose,
    # so sentence capitalization downstream still sees the boundary.
    proj, spans = protect("install to /usr/local/bin. Then run ~/setup.sh.")
    assert spans == ["/usr/local/bin", "~/setup.sh"]
    assert proj == "install to {{R:0}}. Then run {{R:1}}."


def test_protects_version_strings():
    assert _protected("upgrade to v1.2 or 3.4.5 today") == ["v1.2", "3.4.5"]


def test_protects_mention_and_channel():
    assert _protected("hey @alice in #general channel") == ["@alice", "#general"]


# --- negative cases: ordinary prose must survive untouched ------------------------------------


def test_prose_is_not_over_protected():
    text = "and/or on 12/25/2024, pi is 3.14 and he/she agreed"
    proj, spans = protect(text)
    assert spans == []  # no slashes, two-part decimals, or word/word swept up
    assert proj == text


def test_markdown_heading_and_bare_sigils_survive():
    text = "# Heading with a $ sign and a # alone and @ symbol"
    proj, spans = protect(text)
    assert spans == []
    assert proj == text


def test_expanded_round_trips():
    text = "mail me@x.io, run ./go.sh, see [d](https://x.io/d), ping @bob in #ops on v2.0.1"
    proj, spans = protect(text)
    assert restore(proj, spans) == text
