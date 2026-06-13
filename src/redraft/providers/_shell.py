"""Shared runner for providers that shell out to a CLI (command, agent).

Runs ``/bin/sh -c <cmd>`` with the review prompt on stdin and expects the JSON ReviewResult on
stdout. Output is schema-checked here and invariant-checked by the engine, so a misbehaving
command cannot corrupt protected spans.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from typing import TYPE_CHECKING

from redraft.prompt import build_result, extract_json

if TYPE_CHECKING:
    from redraft.base import ReviewResult

# How much of a failed CLI's stderr to include in the error. Generous because the Spoon shows the
# error in a scrollable, copyable modal — enough to read a full auth/usage error (e.g. an agent
# CLI's IneligibleTierError), not just the first line.
_STDERR_LIMIT = 4000


def run(cmd: str, prompt: str, timeout_ms: int, source: str) -> ReviewResult:
    """Run ``cmd`` (via /bin/sh) feeding it ``prompt`` on stdin; parse its JSON stdout.

    ``source`` names the caller for error messages (e.g. "command", "agent:claude").

    Command templates may use:
    - ``{prompt_file}``: replaced with a shell-quoted, mode-0600 temp file containing the prompt.
    - ``{prompt_arg}``: replaced with a shell-quoted prompt argument for CLIs that cannot read
      stdin. The displayed command redacts the prompt; the full prompt is still returned separately.

    If neither placeholder is present, the prompt is passed on stdin for backward compatibility with
    the generic command provider.
    """
    timeout = (timeout_ms or 60000) / 1000
    run_cmd = cmd
    display_cmd = cmd
    input_text = prompt
    prompt_path: str | None = None
    if "{prompt_file}" in run_cmd:
        fd, prompt_path = tempfile.mkstemp(prefix="redraft-prompt-", text=True)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(prompt)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.remove(prompt_path)
            except OSError:
                pass
            raise
        quoted = shlex.quote(prompt_path)
        run_cmd = run_cmd.replace("{prompt_file}", quoted)
        display_cmd = display_cmd.replace("{prompt_file}", "<prompt-file>")
        input_text = None
    if "{prompt_arg}" in run_cmd:
        run_cmd = run_cmd.replace("{prompt_arg}", shlex.quote(prompt))
        display_cmd = display_cmd.replace("{prompt_arg}", "<prompt>")
        input_text = None

    # Appended to every failure so the user can see exactly what ran (templates are config-driven and
    # have {bin} already substituted by the time they reach here). The prompt itself is exposed
    # separately as result.prompt; don't duplicate it in the command field when a prompt placeholder
    # was used.
    where = f"\ncommand: {display_cmd}"
    try:
        try:
            proc = subprocess.run(
                ["/bin/sh", "-c", run_cmd],
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{source} timed out after {int(timeout)}s{where}") from None
        except OSError as e:
            raise RuntimeError(f"failed to run {source}: {e}{where}") from e

        if proc.returncode != 0:
            raise RuntimeError(f"{source} exited {proc.returncode}: {proc.stderr.strip()[:_STDERR_LIMIT]}{where}")

        json_str = extract_json(proc.stdout)
        if not json_str:
            raise RuntimeError(f"{source} produced no JSON object{where}")
        result = build_result(_loads(json_str, source), source)
        result.command = display_cmd
        result.prompt = prompt
        result.raw = proc.stdout  # the CLI's full stdout (chatter + JSON), before extraction
        return result
    finally:
        if prompt_path:
            try:
                os.remove(prompt_path)
            except OSError:
                pass


def _loads(json_str: str, source: str) -> object:
    import json

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        raise RuntimeError(f"{source} output was not valid JSON") from None
