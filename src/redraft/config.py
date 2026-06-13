"""Load ~/.config/redraft/config.json over built-in defaults."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS: dict = {
    "fixProvider": "embedded",
    "improveProvider": "none",
    # Optional: before an Improve provider runs, apply the conservative embedded Fix pass to clean
    # obvious typos/punctuation. Off by default so Improve remains a single explicit transformation
    # unless the user opts into the extra local pre-pass.
    "improve": {"preFix": False},
    # Improve writing style: "friendly" (Slack, default) or "formal" (email). Selects which prompt
    # template the LLM improve providers use (see redraft/prompts/<style>-prompt.txt).
    "improveStyle": "friendly",
    # Spell checking is OFF by default: it can "correct" unrecognized-but-valid words (jargon,
    # product names) into wrong ones, which violates Fix mode's no-meaning-change contract. The
    # curated typo map always runs. Set embedded.spell=true to opt into pyspellchecker (hardened,
    # but still a heuristic).
    "embedded": {"spell": False},
    "ollama": {"url": "http://localhost:11434", "model": "llama3.1:8b"},
    "agent": {"tool": "auto", "timeoutMs": 120000},  # tool: auto|claude|codex|gemini|copilot
    "command": {"cmd": "", "timeoutMs": 60000},
    "languagetool": {"url": "http://localhost:8081", "language": "en-US"},
    # Per-app provider overrides, keyed by frontmost-app bundle id (e.g. "com.tinyspeck.slackmacgap").
    # Each value may set "fixProvider"/"improveProvider"; anything unset falls back to the top-level
    # keys. The Spoon passes the active app's bundle id via `--app`; edit this map in config.json.
    "profiles": {},
    # Which notification types the Spoon surfaces (read only by the Spoon; the engine ignores this).
    # "fix"/"improve" = success toasts per mode; "status" = pause/switch/reload/server messages;
    # "error" = failures. Set any to false to silence that type, e.g. {"fix": false} keeps errors.
    "notifications": {"fix": True, "improve": True, "status": True, "error": True},
}


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "redraft" / "config.json"


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path | None = None) -> dict:
    path = path or config_path()
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    merged = _deep_merge(DEFAULTS, data if isinstance(data, dict) else {})
    # Coerce malformed user config: where a default is a dict, a non-dict override (e.g.
    # `"embedded": "yes"`) is reset to the default so providers can't hit `'str'.get(...)`.
    for key, default in DEFAULTS.items():
        if isinstance(default, dict) and not isinstance(merged.get(key), dict):
            merged[key] = dict(default)
    return merged
