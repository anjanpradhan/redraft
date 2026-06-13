"""Improve provider: hand off to a locally-installed AI agent CLI (Claude/Codex/Gemini/Copilot).

Picks the configured agent (``config.agent.tool``) or, for ``"auto"``, the first one found by
preference order. The binary is resolved **live** — PATH first, then a set of common install dirs —
so an agent installed *after* Redraft works without reconfiguring (the menu/installer also store an
absolute-path hint in ``config.agent.bins`` because the engine runs with a minimal PATH).

Per-agent invocation templates are overridable via ``config.agent.commands.<tool>``. Defaults avoid
``$(cat)`` command substitution; they use ``{prompt_file}`` for CLIs that can read stdin and
``{prompt_arg}`` only for CLIs whose documented non-interactive interface requires an argument.
"""

from __future__ import annotations

import os
import shlex
import shutil
from typing import TYPE_CHECKING

from redraft.prompt import build_prompt
from redraft.providers import _shell

if TYPE_CHECKING:
    from redraft.base import ReviewResult

# tool -> {bin: binary name, template: shell command}
# Placeholders:
#   {bin}         -> shell-quoted binary path
#   {prompt_file} -> shell-quoted temp file containing the full prompt, mode 0600
#   {prompt_arg}  -> shell-quoted prompt argument (argv fallback; avoid unless the CLI requires it)
AGENTS: dict[str, dict[str, str]] = {
    "claude": {"bin": "claude", "template": "{bin} -p < {prompt_file}"},
    # codex exec is non-interactive already; --skip-git-repo-check (engine runs outside a repo) and
    # -s read-only (a text rewrite must never touch the filesystem). "-" makes Codex read stdin.
    "codex": {"bin": "codex", "template": "{bin} exec --skip-git-repo-check -s read-only - < {prompt_file}"},
    # Gemini documents that --prompt is appended to stdin, so pass an empty prompt argument and feed
    # the real prompt through stdin.
    "gemini": {"bin": "gemini", "template": '{bin} -p "" < {prompt_file}'},
    # Copilot's documented non-interactive form requires --prompt <text>; this is the explicit argv
    # fallback and the shell runner redacts the prompt in result.command/error details.
    "copilot": {"bin": "copilot", "template": "{bin} -p {prompt_arg}"},
}
LEGACY_COMMANDS: dict[str, str] = {
    "claude": '{bin} -p "$(cat)"',
    "codex": '{bin} exec --skip-git-repo-check -s read-only "$(cat)"',
    "gemini": '{bin} -p "$(cat)"',
    "copilot": '{bin} -p "$(cat)"',
}
# Order used when tool == "auto".
PREFERENCE = ["claude", "codex", "gemini", "copilot"]


def default_commands() -> dict[str, str]:
    """Default per-agent shell templates (single source of truth).

    The installer seeds these into ``config.agent.commands`` so users can see and edit each agent's
    invocation (flags etc.) without touching code; the engine still falls back to these if a config
    entry is missing.
    """
    return {name: spec["template"] for name, spec in AGENTS.items()}


def legacy_commands() -> dict[str, str]:
    """Old default templates that used ``$(cat)``; installers migrate only exact matches."""
    return dict(LEGACY_COMMANDS)

# Common dirs where agent CLIs land but which may be absent from the engine's PATH under hs.task.
_KNOWN_DIRS = [
    "~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin",
    "~/.npm-global/bin", "~/.bun/bin", "~/.volta/bin", "/usr/bin",
]


def resolve_bin(tool: str, config: dict) -> str | None:
    """Absolute path to ``tool``'s CLI, or None. Order: configured hint -> PATH -> known dirs."""
    spec = AGENTS.get(tool)
    if not spec:
        return None
    binname = spec["bin"]
    hint = (config.get("agent", {}).get("bins", {}) or {}).get(tool)
    if hint and os.path.isfile(os.path.expanduser(hint)) and os.access(os.path.expanduser(hint), os.X_OK):
        return os.path.expanduser(hint)
    found = shutil.which(binname)
    if found:
        return found
    for d in _KNOWN_DIRS:
        p = os.path.join(os.path.expanduser(d), binname)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def review(text: str, mode: str, config: dict) -> ReviewResult:
    agent_cfg = config.get("agent", {})
    tool = agent_cfg.get("tool", "auto")

    if tool == "auto":
        for candidate in PREFERENCE:
            resolved = resolve_bin(candidate, config)
            if resolved:
                tool, bin_path = candidate, resolved
                break
        else:
            raise RuntimeError("no agent CLI found — install claude/codex/gemini/copilot, then pick it in the menu")
    else:
        if tool not in AGENTS:
            raise RuntimeError(f"unknown agent '{tool}' (known: {', '.join(AGENTS)})")
        bin_path = resolve_bin(tool, config)
        if not bin_path:
            raise RuntimeError(f"agent '{tool}' not found on PATH or known locations; is it installed?")

    template = (agent_cfg.get("commands", {}) or {}).get(tool) or AGENTS[tool]["template"]
    cmd = template.replace("{bin}", shlex.quote(bin_path))
    prompt = build_prompt(mode, text, config)
    result = _shell.run(cmd, prompt, agent_cfg.get("timeoutMs", 120000), f"agent:{tool}")
    result.change_notes = [f"via {tool}", *result.change_notes]
    return result
