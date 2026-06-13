"""Embedded Fix provider — deterministic, in-process.

A curated typo/contraction map + ``i`` -> ``I`` + abbreviation-aware sentence capitalization +
safe whitespace/punctuation tidies. Operates only on the text *between* protected ``{{R:n}}``
tokens, so tokens are never touched.

If the optional ``pyspellchecker`` package is installed (``pip install "redraft[nlp]"``) and
``config.embedded.spell`` is enabled (**opt-in; OFF by default**), unknown lowercase words are
additionally spell-corrected under a hardened gate (single edit distance, common-word candidate,
jargon allowlist) — because a dictionary checker otherwise "corrects" valid-but-unknown terms
(webhook->rebook). Default behavior is the deterministic curated map only.
"""

from __future__ import annotations

import re

from redraft.base import ReviewResult

_SPLIT_RE = re.compile(r"(\{\{R:\d+\}\})")
# Unicode-aware word matcher (letters + internal apostrophes); keeps words like "café" whole.
_WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*", re.UNICODE)

FIXES = {
    "teh": "the",
    "adn": "and",
    "recieve": "receive",
    "recieved": "received",
    "seperate": "separate",
    "definately": "definitely",
    "occured": "occurred",
    "untill": "until",
    "wich": "which",
    "thier": "their",
    "becuase": "because",
    "accross": "across",
    "tommorow": "tomorrow",
    "tommorrow": "tomorrow",
    "enviroment": "environment",
    "neccessary": "necessary",
    "occassionally": "occasionally",
    "wierd": "weird",
    "acheive": "achieve",
    "beleive": "believe",
    "calender": "calendar",
    "collegue": "colleague",
    "concious": "conscious",
    "embarass": "embarrass",
    "goverment": "government",
    "independant": "independent",
    "occurance": "occurrence",
    "priviledge": "privilege",
    "reccomend": "recommend",
    "refered": "referred",
    "succesful": "successful",
    "wether": "whether",
    "youre": "you're",
    "cant": "can't",
    "dont": "don't",
    "wont": "won't",
    "isnt": "isn't",
    "arent": "aren't",
    "wasnt": "wasn't",
    "werent": "weren't",
    "didnt": "didn't",
    "doesnt": "doesn't",
    "couldnt": "couldn't",
    "shouldnt": "shouldn't",
    "wouldnt": "wouldn't",
    "im": "I'm",
    "ive": "I've",
    "thats": "that's",
    "whats": "what's",
    "hasnt": "hasn't",
    "havent": "haven't",
}

# Common lowercase technical terms the spell checker would otherwise "correct" — treated as known.
_TECH_WORDS = [
    "repo",
    "repos",
    "async",
    "await",
    "env",
    "envs",
    "config",
    "configs",
    "dev",
    "prod",
    "staging",
    "args",
    "kwargs",
    "json",
    "yaml",
    "yml",
    "regex",
    "stdin",
    "stdout",
    "stderr",
    "url",
    "uri",
    "api",
    "apis",
    "sdk",
    "cli",
    "sql",
    "jwt",
    "oauth",
    "kube",
    "kubectl",
    "namespace",
    "namespaces",
    "middleware",
    "backend",
    "frontend",
    "runtime",
    "localhost",
    "hostname",
    "timestamp",
    "changelog",
    "dataset",
    "datasets",
    "enum",
    "struct",
    "bool",
]

# Abbreviations that end in "." but do NOT end a sentence (so we don't wrongly capitalize after).
_ABBREV = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "mt",
        "no",
        "vs",
        "etc",
        "al",
        "approx",
        "inc",
        "ltd",
        "co",
        "corp",
        "dept",
        "est",
        "fig",
        "vol",
        "cf",
        "ca",
        "dec",
        "jan",
        "feb",
        "e.g",
        "i.e",
        "a.m",
        "p.m",
        "u.s",
        "u.k",
        "ph.d",
        "b.a",
        "m.a",
        "n.b",
    }
)
# A spell correction only fires if its candidate is at least this common (fraction of the corpus).
# Tuned so real typos (spelling 3.2e-6, environment 8.8e-6) pass but distance-1 collisions with
# rare words (rebase->debase 2e-7, dedupe->deduce 1.1e-6) are rejected. Spell is OFF by default
# (embedded.spell); this only governs the opt-in path.
_MIN_CORR_USAGE = 2.5e-6

_spell = None
_spell_loaded = False


def _get_spell() -> object | None:  # a SpellChecker, or None when unavailable/failed
    global _spell, _spell_loaded
    if not _spell_loaded:
        _spell_loaded = True
        try:
            from spellchecker import SpellChecker

            _spell = SpellChecker(distance=1)  # only single-edit typos; avoids most false positives
            _spell.word_frequency.load_words(_TECH_WORDS)
        except Exception:
            _spell = None
    return _spell


def _match_case(orig: str, repl: str) -> str:
    if orig[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def _spell_fix(w: str, spell: object | None) -> str | None:
    # Conservative: lowercase, pure-ASCII, alphabetic, length >= 4, flagged unknown, with a single
    # edit-distance candidate that is itself a reasonably common word (so we don't "correct" an
    # unrecognized-but-valid term into a rare neighbour, e.g. rebase->debase).
    if spell is None or len(w) < 4 or not w.isascii() or not w.isalpha() or not w.islower():
        return None
    if not spell.unknown([w]):  # already a known word
        return None
    cand = spell.correction(w)
    if not cand or cand == w:
        return None
    wf = spell.word_frequency
    if wf.total_words and (wf[cand] / wf.total_words) < _MIN_CORR_USAGE:
        return None
    return cand


# Sentence boundary: a token, its terminal .!? , whitespace, then a lowercase letter to capitalize.
_CAP_RE = re.compile(r"(\S+)([.!?])(\s+)([a-z])")


def _cap_sentence(m: re.Match[str]) -> str:
    token = m.group(1).lower().strip("\"'()[]{}*_")
    if token in _ABBREV:  # not a real sentence end (e.g. "p.m.", "etc.") — leave as-is
        return m.group(0)
    return m.group(1) + m.group(2) + m.group(3) + m.group(4).upper()


def _fix_segment(seg: str, notes: list[str], is_start: bool, spell: object | None) -> str:
    def word_repl(m: re.Match[str]) -> str:
        w = m.group(0)
        if w == "i":
            repl = "I"
        else:
            mapped = FIXES.get(w.lower())
            repl = _match_case(w, mapped) if mapped else _spell_fix(w, spell)
        if repl and repl != w:
            notes.append(f"{w} → {repl}")
            return repl
        return w

    seg = _WORD_RE.sub(word_repl, seg)
    seg = re.sub(r" {2,}", " ", seg)  # collapse runs of spaces
    seg = re.sub(r"\s+([,.!?;:])", r"\1", seg)  # drop space before punctuation
    # NB: no doubled-word collapse — it deletes legitimate repeats and numbers ("had had", "5 5").
    seg = _CAP_RE.sub(_cap_sentence, seg)  # capitalize sentence starts (skipping abbreviations)
    if is_start:  # capitalize the very first letter
        seg = re.sub(r"^(\s*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), seg)
    return seg


def review(text: str, mode: str, config: dict) -> ReviewResult:  # noqa: ARG001 — mode unused
    emb = config.get("embedded") if isinstance(config.get("embedded"), dict) else {}
    spell = _get_spell() if emb.get("spell", False) else None  # opt-in; see config.py
    notes: list[str] = []
    parts = _SPLIT_RE.split(text)  # even indices = prose, odd = tokens
    for i in range(0, len(parts), 2):
        parts[i] = _fix_segment(parts[i], notes, is_start=(i == 0), spell=spell)
    return ReviewResult(revised="".join(parts), change_notes=notes)
