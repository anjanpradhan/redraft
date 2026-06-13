"""Provider registry + selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import agent, command, embedded, languagetool, ollama

if TYPE_CHECKING:
    from types import ModuleType

# name -> module exposing review(text, mode, config) -> ReviewResult
_REGISTRY: dict[str, ModuleType] = {
    "embedded": embedded,
    "languagetool": languagetool,
    "ollama": ollama,
    "command": command,
    "agent": agent,
}
_MODES = {
    "embedded": {"fix"},
    "languagetool": {"fix"},
    "ollama": {"improve"},
    "command": {"fix", "improve"},
    "agent": {"improve"},
}


def pick_provider(mode: str, config: dict, app: str | None = None) -> ModuleType:
    key = "fixProvider" if mode == "fix" else "improveProvider"
    # A per-app profile (keyed by the frontmost app's bundle id) overrides the top-level provider
    # for that app; anything it leaves unset falls back to the global key.
    profiles = config.get("profiles")
    profile = profiles.get(app) if isinstance(profiles, dict) and app else None
    name = (profile.get(key) if isinstance(profile, dict) else None) or config.get(key, "embedded")
    if name == "none":
        raise RuntimeError(f"{mode} provider not configured — pick one in the Redraft menu")
    provider = _REGISTRY.get(name)
    if provider is None:
        raise RuntimeError(f"unknown provider '{name}' for {mode} mode")
    if mode not in _MODES[name]:
        allowed = ", ".join(sorted(_MODES[name]))
        raise RuntimeError(f"provider '{name}' is not available for {mode} mode (allowed: {allowed})")
    return provider
