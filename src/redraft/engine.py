"""Core pipeline: protect -> provider -> token invariant -> restore."""

from __future__ import annotations

import re

from .base import ReviewError
from .protect import check_invariant, protect, restore
from .providers import embedded as embedded_provider
from .providers import pick_provider

_MAX_INVARIANT_RETRIES = 1  # resample an LLM provider once if it drops/dups a {{R:n}} token
_TOKEN_RE = re.compile(r"\{\{R:(\d+)\}\}")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_REPAIR_CONTEXT_WORDS = 3


def _normalize_escaped_newlines(original: str, revised: str) -> str:
    """Repair providers that double-escape multiline output as literal ``\n`` text."""
    if "\n" not in original or "\\n" not in revised:
        return revised
    candidate = revised.replace("\\r\\n", "\n").replace("\\n", "\n")
    if "\n" not in revised:
        return candidate
    original_line_count = len(_line_shape(original)[1])
    revised_distance = abs(len(_line_shape(revised)[1]) - original_line_count)
    candidate_distance = abs(len(_line_shape(candidate)[1]) - original_line_count)
    return candidate if candidate_distance < revised_distance else revised


def _normalize_escaped_tabs(original: str, revised: str) -> str:
    """Repair providers that double-escape tabs as literal ``\\t`` text."""
    if "\\t" not in revised:
        return revised
    if "\t" in original:
        return revised.replace("\\t", "\t")
    if "\\t" in original:
        return revised
    return revised.replace("\\t", "  ")


def _normalize_visible_escape_sequences(original: str, revised: str) -> str:
    """Repair providers that expose JSON/string escapes as visible prose."""
    replacements = {
        "\\'": "'",
        "\\u0027": "'",
        "\\u2018": "\u2018",
        "\\u2019": "\u2019",
        "\\u201c": "\u201c",
        "\\u201d": "\u201d",
        "\\u2013": "\u2013",
        "\\u2014": "\u2014",
        "\\u2026": "\u2026",
    }
    for escaped, replacement in replacements.items():
        if escaped in revised and escaped not in original:
            revised = revised.replace(escaped, replacement)
    return revised


def _line_shape(text: str) -> tuple[str, list[str], list[str], str]:
    """Return prefix, non-empty lines, separators between them, and suffix."""
    prefix = ""
    suffix = ""
    lines: list[str] = []
    separators: list[str] = []
    pending = ""
    seen_line = False
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        newline = line[len(content) :]
        if content.strip():
            if seen_line:
                separators.append(pending)
            else:
                prefix = pending
            lines.append(content)
            pending = newline
            seen_line = True
        elif seen_line:
            pending += line
        else:
            pending += line
    if seen_line:
        suffix = pending
    else:
        prefix = pending
    return prefix, lines, separators, suffix


def _restore_line_separators(original: str, revised: str) -> str:
    """Keep paragraph spacing when a provider returns the same non-empty line shape."""
    if "\n" not in original or "\n" not in revised:
        return revised
    _oprefix, original_lines, original_separators, _osuffix = _line_shape(original)
    revised_prefix, revised_lines, _revised_separators, revised_suffix = _line_shape(revised)
    if len(original_lines) <= 1 or len(original_lines) != len(revised_lines):
        return revised
    out = revised_prefix + revised_lines[0]
    for separator, line in zip(original_separators, revised_lines[1:], strict=True):
        out += separator + line
    return out + revised_suffix


def _normalize_multiline_output(original: str, revised: str) -> str:
    revised = _normalize_escaped_newlines(original, revised)
    revised = _normalize_escaped_tabs(original, revised)
    revised = _normalize_visible_escape_sequences(original, revised)
    return _restore_line_separators(original, revised)


def _words(text: str) -> list[str]:
    return [match.group(0).lower() for match in _WORD_RE.finditer(_TOKEN_RE.sub(" ", text))]


def _collapsed_token_has_context(projection: str, token_id: int, candidate: str, match: re.Match[str]) -> bool:
    token = f"{{{{R:{token_id}}}}}"
    start = projection.find(token)
    if start < 0 or projection.find(token, start + len(token)) >= 0:
        return False

    before_words = _words(projection[:start])[-_REPAIR_CONTEXT_WORDS:]
    after_words = _words(projection[start + len(token) :])[:_REPAIR_CONTEXT_WORDS]
    if not before_words and not after_words:
        return False

    if before_words:
        candidate_before = _words(candidate[: match.start()])[-len(before_words) :]
        if candidate_before != before_words:
            return False
    if after_words:
        candidate_after = _words(candidate[match.end() :])[: len(after_words)]
        if candidate_after != after_words:
            return False
    return True


def _repair_collapsed_token_ids(projection: str, count: int, revised: str) -> str:
    """Repair LLMs that turn ``{{R:0}}`` into the bare id ``0``.

    This is intentionally narrow: every missing token id must have exactly one standalone numeric
    occurrence in the original token's local context, and the repaired candidate must satisfy the
    normal invariant.
    """
    if count == 0:
        return revised

    seen: dict[int, int] = {}
    for match in _TOKEN_RE.finditer(revised):
        token_id = int(match.group(1))
        if token_id < 0 or token_id >= count:
            return revised
        seen[token_id] = seen.get(token_id, 0) + 1

    missing = [i for i in range(count) if seen.get(i, 0) == 0]
    if not missing or any(seen.get(i, 0) > 1 for i in range(count)):
        return revised

    candidate = revised
    for token_id in missing:
        # Standalone ids only: not words, versions/decimals, signs, ranges, or "R:0" fragments.
        pattern = re.compile(rf"(?<![\w.+:-]){token_id}(?![\w:-]|\.\d)")
        matches = list(pattern.finditer(candidate))
        if len(matches) != 1:
            return revised
        if not _collapsed_token_has_context(projection, token_id, candidate, matches[0]):
            return revised
        candidate = pattern.sub(f"{{{{R:{token_id}}}}}", candidate, count=1)

    ok, _reason = check_invariant(count, candidate)
    return candidate if ok else revised


def review(text: str, mode: str, config: dict, app: str | None = None) -> dict:
    """Return {revised, change_notes, risk_flags, provider, mode}.

    ``app`` is the frontmost app's bundle id (optional); it selects a per-app provider profile.
    Raises RuntimeError on provider failure or token-invariant violation (caller leaves the
    user's text untouched).
    """
    if mode not in ("fix", "improve"):
        raise RuntimeError(f"unknown mode: {mode}")

    provider = pick_provider(mode, config, app)
    provider_name = getattr(provider, "__name__", "").rsplit(".", 1)[-1] or "?"

    def tag_error(e: ReviewError) -> None:
        if not e.provider:
            e.provider = provider_name
        if not e.mode:
            e.mode = mode

    projection, spans = protect(text)
    structure_baseline = text
    pre_notes: list[str] = []
    if mode == "improve":
        pre_result = embedded_provider.review(projection, "fix", config)
        ok, reason = check_invariant(len(spans), pre_result.revised)
        if not ok:
            raise RuntimeError(f"pre-fix token invariant violated ({reason}); leaving text unchanged")
        projection = pre_result.revised
        structure_baseline = restore(projection, spans)
        pre_notes = [f"pre-fix: {note}" for note in pre_result.change_notes]

    try:
        result = provider.review(projection, mode, config)
    except ReviewError as e:
        tag_error(e)
        raise
    result.revised = _normalize_multiline_output(structure_baseline, result.revised)
    if result.prompt is not None:
        result.revised = _repair_collapsed_token_ids(projection, len(spans), result.revised)
    ok, reason = check_invariant(len(spans), result.revised)
    restored = restore(result.revised, spans) if ok else ""

    # An LLM provider (result.prompt is set) can drop or duplicate a {{R:n}} token; at temperature a
    # fresh sample often gets it right. Deterministic providers (embedded, languagetool) edit only the
    # prose between tokens and never fail this, so we don't waste a round-trip resampling them.
    retries = _MAX_INVARIANT_RETRIES if result.prompt is not None else 0
    for _ in range(retries):
        if ok:
            break
        try:
            result = provider.review(projection, mode, config)
        except ReviewError as e:
            tag_error(e)
            raise
        result.revised = _normalize_multiline_output(structure_baseline, result.revised)
        if result.prompt is not None:
            result.revised = _repair_collapsed_token_ids(projection, len(spans), result.revised)
        ok, reason = check_invariant(len(spans), result.revised)
        restored = restore(result.revised, spans) if ok else ""

    if not ok:
        raise ReviewError(
            f"output invariant violated ({reason}); leaving text unchanged",
            provider=provider_name,
            mode=mode,
            command=result.command,
            prompt=result.prompt,
            raw=result.raw,
        )

    out = {
        "revised": restored,
        "change_notes": pre_notes + result.change_notes,
        "risk_flags": result.risk_flags,
        "provider": provider_name,
        "mode": mode,
    }
    if result.command:  # shell-based providers report the resolved command display (transparency)
        out["command"] = result.command
    if result.prompt:  # LLM providers report the full prompt sent to the model
        out["prompt"] = result.prompt
    if result.raw:  # the model/CLI's raw response, before extraction/restoration
        out["raw"] = result.raw
    return out
