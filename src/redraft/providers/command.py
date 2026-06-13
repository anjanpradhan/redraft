"""Provider that shells out to a locally-installed CLI/agent (configured via config.command.cmd).

The command reads the full prompt on stdin and must print the JSON ReviewResult on stdout.
Output is still schema- and (by the engine) invariant-checked, so a misbehaving command cannot
corrupt protected spans.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from redraft.prompt import build_prompt
from redraft.providers import _shell

if TYPE_CHECKING:
    from redraft.base import ReviewResult


def review(text: str, mode: str, config: dict) -> ReviewResult:
    cmd_cfg = config.get("command", {})
    # Per-mode command (command.fixCmd / command.improveCmd) wins, falling back to a shared
    # command.cmd — so Fix and Improve can use different CLIs.
    cmd = cmd_cfg.get(f"{mode}Cmd") or cmd_cfg.get("cmd", "")
    if not cmd:
        raise RuntimeError(f"command provider not configured (set command.{mode}Cmd or command.cmd)")
    prompt = build_prompt(mode, text, config)
    return _shell.run(cmd, prompt, cmd_cfg.get("timeoutMs", 60000), "command")
