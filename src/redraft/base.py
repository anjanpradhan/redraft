"""Provider contract + result type."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ReviewResult:
    revised: str
    change_notes: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    # The resolved shell command display for this result (set by shell-based providers: command,
    # agent). Prompt placeholders may be redacted; the full prompt is carried separately below.
    # None for in-process/HTTP providers. Surfaced for transparency/debugging.
    command: str | None = None
    # The full prompt sent to the model (set by LLM providers: command, agent, ollama). Contains the
    # protected projection (so {{R:n}} tokens are visible — that's literally what the model saw).
    # None for deterministic providers (embedded, languagetool).
    prompt: str | None = None
    # The raw, unprocessed response from the model/CLI (full stdout for shell providers; the message
    # content for ollama) — before JSON extraction / token restoration. Surfaced for debugging.
    raw: str | None = None


class ReviewError(RuntimeError):
    """Engine error with provider context that the UI can surface for debugging."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        mode: str | None = None,
        command: str | None = None,
        prompt: str | None = None,
        raw: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.mode = mode
        self.command = command
        self.prompt = prompt
        self.raw = raw

    def to_dict(self) -> dict[str, str]:
        out = {"error": str(self)}
        if self.provider:
            out["provider"] = self.provider
        if self.mode:
            out["mode"] = self.mode
        if self.command:
            out["command"] = self.command
        if self.prompt:
            out["prompt"] = self.prompt
        if self.raw:
            out["raw"] = self.raw
        return out


class Provider(Protocol):
    name: str

    def review(self, text: str, mode: str, config: dict) -> ReviewResult:
        """Given a protected projection, return the revised projection (tokens preserved)."""
        ...
