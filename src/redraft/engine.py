"""Core pipeline: protect -> provider -> token invariant -> restore."""

from __future__ import annotations

from .protect import check_invariant, protect, restore
from .providers import embedded as embedded_provider
from .providers import pick_provider

_MAX_INVARIANT_RETRIES = 1  # resample an LLM provider once if it drops/dups a {{R:n}} token


def _improve_prefix_enabled(config: dict) -> bool:
    improve = config.get("improve")
    return isinstance(improve, dict) and improve.get("preFix") is True


def review(text: str, mode: str, config: dict, app: str | None = None) -> dict:
    """Return {revised, change_notes, risk_flags, provider, mode}.

    ``app`` is the frontmost app's bundle id (optional); it selects a per-app provider profile.
    Raises RuntimeError on provider failure or token-invariant violation (caller leaves the
    user's text untouched).
    """
    if mode not in ("fix", "improve"):
        raise RuntimeError(f"unknown mode: {mode}")

    projection, spans = protect(text)
    pre_notes: list[str] = []
    if mode == "improve" and _improve_prefix_enabled(config):
        pre_result = embedded_provider.review(projection, "fix", config)
        ok, reason = check_invariant(len(spans), pre_result.revised)
        if not ok:
            raise RuntimeError(f"pre-fix token invariant violated ({reason}); leaving text unchanged")
        projection = pre_result.revised
        pre_notes = [f"pre-fix: {note}" for note in pre_result.change_notes]

    provider = pick_provider(mode, config, app)
    result = provider.review(projection, mode, config)
    ok, reason = check_invariant(len(spans), result.revised)

    # An LLM provider (result.prompt is set) can drop or duplicate a {{R:n}} token; at temperature a
    # fresh sample often gets it right. Deterministic providers (embedded, languagetool) edit only the
    # prose between tokens and never fail this, so we don't waste a round-trip resampling them.
    retries = _MAX_INVARIANT_RETRIES if result.prompt is not None else 0
    for _ in range(retries):
        if ok:
            break
        result = provider.review(projection, mode, config)
        ok, reason = check_invariant(len(spans), result.revised)

    if not ok:
        raise RuntimeError(f"token invariant violated ({reason}); leaving text unchanged")

    out = {
        "revised": restore(result.revised, spans),
        "change_notes": pre_notes + result.change_notes,
        "risk_flags": result.risk_flags,
        "provider": getattr(provider, "__name__", "").rsplit(".", 1)[-1] or "?",
        "mode": mode,
    }
    if result.command:  # shell-based providers report the resolved command display (transparency)
        out["command"] = result.command
    if result.prompt:  # LLM providers report the full prompt sent to the model
        out["prompt"] = result.prompt
    if result.raw:  # the model/CLI's raw response, before extraction/restoration
        out["raw"] = result.raw
    return out
