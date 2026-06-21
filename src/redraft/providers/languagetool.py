"""Fix provider: deterministic grammar/spell via a local LanguageTool server (HTTP)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from redraft.base import ReviewResult

_TOKEN_RE = re.compile(r"\{\{R:\d+\}\}")


def _utf16_to_py_index(text: str, offset: int) -> int | None:
    """Convert a Java/LanguageTool UTF-16 code-unit offset into a Python string index."""
    if offset < 0:
        return None
    units = 0
    for i, ch in enumerate(text):
        if units == offset:
            return i
        width = 2 if ord(ch) > 0xFFFF else 1
        if units + width > offset:
            return None  # offset lands in the middle of a surrogate pair
        units += width
    return len(text) if units == offset else None


def review(text: str, mode: str, config: dict) -> ReviewResult:  # noqa: ARG001
    lt = config.get("languagetool", {})
    url = lt.get("url", "http://localhost:8081").rstrip("/") + "/v2/check"
    body = urllib.parse.urlencode({"language": lt.get("language", "en-US"), "text": text}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"cannot reach LanguageTool at {url} ({e}); is the server running?") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"LanguageTool at {url} returned a non-JSON response; is :8081 really LanguageTool?"
        ) from None
    if not isinstance(data, dict):
        raise RuntimeError(f"unexpected LanguageTool response from {url}")

    token_spans = [(m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]

    def overlaps_token(start: int, end: int) -> bool:
        return any(start < te and end > ts for ts, te in token_spans)

    candidates = []
    for seq, m in enumerate(data.get("matches", [])):
        reps = m.get("replacements") or []
        if not reps:
            continue
        offset, length = m.get("offset"), m.get("length")
        if not isinstance(offset, int) or not isinstance(length, int) or length < 0:
            continue
        start = _utf16_to_py_index(text, offset)
        end = _utf16_to_py_index(text, offset + length)
        if start is None or end is None or end < start or overlaps_token(start, end):
            continue
        value = reps[0].get("value", "")
        candidates.append((start, end, str(value), seq))

    edits = []
    occupied_until = -1
    for start, end, value, _seq in sorted(candidates, key=lambda e: (e[0], -(e[1] - e[0]), e[3])):
        if start < occupied_until:
            continue
        edits.append((start, end, value))
        occupied_until = end

    edits.sort(key=lambda e: e[0], reverse=True)  # right-to-left keeps offsets valid
    revised, notes = text, []
    for start, end, value in edits:
        before = revised[start:end]
        revised = revised[:start] + value + revised[end:]
        notes.append(f"{before!r} → {value!r}")
    return ReviewResult(revised=revised, change_notes=notes)
