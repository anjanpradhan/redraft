"""Fix provider: deterministic grammar/spell via a local LanguageTool server (HTTP)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from redraft.base import ReviewResult

_TOKEN_RE = re.compile(r"\{\{R:\d+\}\}")


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

    def overlaps_token(start: int, length: int) -> bool:
        end = start + length
        return any(start < te and end > ts for ts, te in token_spans)

    edits = []
    for m in data.get("matches", []):
        reps = m.get("replacements") or []
        if not reps:
            continue
        offset, length = m.get("offset", 0), m.get("length", 0)
        if overlaps_token(offset, length):
            continue
        edits.append((offset, length, reps[0].get("value", "")))

    edits.sort(key=lambda e: e[0], reverse=True)  # right-to-left keeps offsets valid
    revised, notes = text, []
    for offset, length, value in edits:
        before = revised[offset : offset + length]
        revised = revised[:offset] + value + revised[offset + length :]
        notes.append(f"{before!r} → {value!r}")
    return ReviewResult(revised=revised, change_notes=notes)
