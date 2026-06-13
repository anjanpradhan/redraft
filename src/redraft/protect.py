"""Protect technical entities before review, and restore them after.

Protects high-signal technical spans by replacing each with an opaque ``{{R:n}}`` token:
`inline code`, [markdown](links), URLs, emails, ``$ENV`` vars, file paths, version strings,
``@mentions``, and ``#channels``. Providers must echo every token unchanged; ``check_invariant``
enforces that (a multiset check) so a provider can never corrupt them — a violation is rejected
and the text left untouched.

Every auto-protected span is **sigil-anchored** (a backtick, ``http``, ``@…\\.`` shape, ``$``, a
leading ``./``/``../``/``~/`` or a multi-segment ``/abs/path``, a ``v``-prefix or 3+ dotted parts,
``@``/``#``) so ordinary prose is never swept up — e.g. ``and/or``, ``12/25/2024``, ``3.14`` and a
markdown ``# Heading`` are left alone. Other unformatted plaintext (``p95``, ``POST /v1/foo``) is
NOT auto-protected; wrap it in backticks to protect it.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"\{\{R:(\d+)\}\}")
# Alternation is tried in order at each position (first match wins), so ordering matters: a literal
# user-typed token first (round-trips instead of colliding with our namespace), code before the
# markdown/URL rules, markdown-link before URL (so the inner URL isn't split out), email before the
# bare @mention rule. Each part is sigil-anchored to stay high-precision (see module docstring).
_PROTECT_PARTS = [
    r"\{\{R:\d+\}\}",  # a literal {{R:n}} the user typed
    r"`[^`\n]+`",  # `inline code`
    r"\[[^\]\n]+\]\([^)\s]+\)",  # [markdown](links) — before URL
    r"https?://[^\s<>()]*[^\s<>().,;:!?]",  # URLs (minus trailing sentence punctuation)
    r"[\w.+-]+@[\w-]+\.[\w.-]*\w",  # emails (mandatory trailing \w drops a sentence period)
    r"\$\{[A-Za-z_]\w*\}|\$[A-Za-z_]\w*",  # env vars: ${FOO} or $FOO
    # paths: ./ ../ ~/ rel, or /abs (>=2 segments). The (?<![\w/]) anchor keeps a path's leading
    # slash off a word/digit, so dates ("12/25/2024") and word/word ("and/or") aren't mistaken for
    # one; the trailing (?<!\.) drops a sentence-ending period ("see /usr/bin.") back into the prose
    # (internal dots in extensions like app.py are kept), mirroring the URL rule.
    r"(?<![\w/])(?:(?:\.\.?/|~/)[\w./~-]+|/[\w.~-]+(?:/[\w.~-]*)+)(?<!\.)",
    r"\bv\d+(?:\.\d+)*|\b\d+\.\d+\.\d+(?:\.\d+)*",  # versions: v1 / v1.2.3, or bare 3+ part 1.2.3
    r"@[\w][\w-]*",  # @mentions (emails consumed above)
    r"#[\w][\w-]*",  # #channels / #refs (markdown "# heading" has a space after #)
]
_PROTECT_RE = re.compile("|".join(_PROTECT_PARTS))


def protect(text: str) -> tuple[str, list[str]]:
    """Return (projection, spans) with protected spans replaced by ``{{R:n}}`` tokens."""
    spans: list[str] = []

    def repl(m: re.Match[str]) -> str:
        spans.append(m.group(0))
        return f"{{{{R:{len(spans) - 1}}}}}"

    return _PROTECT_RE.sub(repl, text), spans


def restore(text: str, spans: list[str]) -> str:
    """Expand ``{{R:n}}`` tokens back to their original spans. Run only after the invariant holds."""

    def repl(m: re.Match[str]) -> str:
        i = int(m.group(1))
        return spans[i] if 0 <= i < len(spans) else m.group(0)

    return _TOKEN_RE.sub(repl, text)


def check_invariant(count: int, text: str) -> tuple[bool, str | None]:
    """Each token id 0..count-1 must appear exactly once (multiset; order may change).

    Any unknown / out-of-range token id is a rejection. Returns (ok, reason).
    """
    seen: dict[int, int] = {}
    for m in _TOKEN_RE.finditer(text):
        i = int(m.group(1))
        if i < 0 or i >= count:
            return False, f"unknown token {{{{R:{i}}}}}"
        seen[i] = seen.get(i, 0) + 1
    for i in range(count):
        c = seen.get(i, 0)
        if c != 1:
            return False, f"token {{{{R:{i}}}}} appears {c}x, expected 1"
    return True, None
