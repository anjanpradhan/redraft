import pytest

from redraft.providers import embedded

SPELL = {"embedded": {"spell": True}}  # spell is opt-in (off by default)


def _fix(text: str, config: dict | None = None) -> str:
    return embedded.review(text, "fix", config or {}).revised


# --- curated map + tidies (no spell checker needed) ------------------------------------------


def test_typos_and_contractions():
    assert _fix("teh") == "The"  # also sentence-cap at start
    assert _fix("i dont know") == "I don't know"


def test_standalone_i():
    assert _fix("when i go") == "When i go".replace("i", "I", 1)


def test_capitalizes_sentences():
    assert _fix("hello. there it is") == "Hello. There it is"
    assert _fix("cost was 50. we agreed") == "Cost was 50. We agreed"  # caps after number-ended sentence


def test_does_not_capitalize_after_abbreviations():
    assert _fix("we met at 3 p.m. and ran") == "We met at 3 p.m. and ran"
    assert _fix("apples, etc. but also pears") == "Apples, etc. but also pears"


def test_preserves_tokens():
    out = _fix("teh {{R:0}} adn {{R:1}}")
    assert "{{R:0}}" in out
    assert "{{R:1}}" in out
    assert "The" in out  # 'teh' fixed + capitalized at start
    assert "and" in out  # 'adn' fixed


def test_tidies_whitespace_and_punctuation():
    assert _fix("hi  there ,  ok") == "Hi there, ok"


def test_does_not_delete_doubled_words_or_numbers():
    # The old doubled-word collapse destroyed legitimate repeats/numbers — must NOT happen.
    assert _fix("I had had enough") == "I had had enough"
    assert _fix("ship 10 10 units") == "Ship 10 10 units"


# --- optional spell checker (skips if pyspellchecker isn't installed) -------------------------

pytest.importorskip("spellchecker")


def test_spell_off_by_default():
    assert _fix("wrold") == "Wrold"  # capitalized but NOT corrected (spell off)


def test_spell_corrects_real_typos_when_enabled():
    assert _fix("wrold", SPELL) == "World"
    assert _fix("the enviroment", SPELL) == "The environment"
    assert "spelling" in _fix("bad speling here", SPELL).lower()


def test_spell_does_not_corrupt_technical_words():
    # The H1 regression: unknown-but-valid terms must survive (no debase/deduce/tempting/rebook).
    for word in ("webhook", "rebase", "dedupe", "templating", "kubectl", "middleware"):
        assert word in _fix(f"please {word} it", SPELL), word


def test_spell_skips_proper_nouns_acronyms_short_nonascii():
    assert "Kubernetes" in _fix("we use Kubernetes", SPELL)  # has uppercase
    assert "API" in _fix("call the API", SPELL)  # acronym
    assert _fix("a café here", SPELL) == "A café here"  # non-ASCII untouched


def test_spell_preserves_tokens():
    out = _fix("wrold {{R:0}} speling", SPELL)
    assert "{{R:0}}" in out
    assert "World" in out


def test_deterministic():
    assert _fix("teh wrold and speling", SPELL) == _fix("teh wrold and speling", SPELL)
